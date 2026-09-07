#!/usr/bin/env bash
# Install and register a self-hosted GitHub Actions runner ON THE BOX IT DEPLOYS.
#
#   deploy/install-runner.sh <prod|staging>
#
# The registration token comes from the environment, never from a file and never from
# this repository:
#
#   RUNNER_TOKEN=AXXXX... deploy/install-runner.sh prod
#
# Mint one at  Settings -> Actions -> Runners -> New self-hosted runner  (it is valid for
# one hour and for one registration). It is NOT a PAT: it cannot read the repository and
# it expires on its own, which is exactly why the runbook uses it rather than a PAT.
#
# WHY A DEPLOY RUNNER LIVES HERE AT ALL: with a runner on this machine the deploy job is
# a local operation -- rsync between two directories, then deploy/deploy.sh -- so GitHub
# never opens a connection INTO the box. No inbound port is opened by this script; the
# runner dials out to GitHub on 443 and long-polls, the same direction as `git push`.
set -euo pipefail

REPO_URL="https://github.com/137mallory/kssl-deploy"
RUNNER_DIR="/opt/actions-runner"
LABEL="${1:?usage: install-runner.sh <prod|staging>}"

case "$LABEL" in
  prod|staging) ;;
  *) echo "!! label must be 'prod' or 'staging', not '$LABEL'"; exit 2 ;;
esac

[ "$(id -u)" -eq 0 ] || { echo "!! run as root: the deploy reads /opt/kssl/app/.env (root:root 600)"; exit 2; }

# THE GUARD THAT MAKES A MISLABELLED RUNNER IMPOSSIBLE TO CREATE.
#
# Every other wrong-environment control in this repository is checked at DEPLOY time --
# the label pair in `runs-on`, the marker step in deploy.yml, the same check again inside
# deploy.sh. All three are downstream of this one decision: which label this machine was
# registered with. Ask the machine itself, here, once, and the later checks have nothing
# left to catch.
MARKER="/opt/kssl/app/.KSSL_ENV"
HOST_ENV="$(tr -d '[:space:]' < "$MARKER" 2>/dev/null || true)"
if [ -z "$HOST_ENV" ]; then
  echo "!! $MARKER is missing, so this machine has not been provisioned as any"
  echo "   environment. Run deploy/provision_env.sh first. Refusing to register a runner"
  echo "   whose environment cannot be proved."
  exit 5
fi
if [ "$HOST_ENV" != "$LABEL" ]; then
  echo "!! REFUSING: this machine is provisioned as '$HOST_ENV', but you asked to register"
  echo "   it as '$LABEL'. A runner with the wrong label would be offered the wrong"
  echo "   environment's deploy job. Register it as '$HOST_ENV'."
  exit 5
fi
echo ">> machine marker '$HOST_ENV' matches the requested label"

: "${RUNNER_TOKEN:?set RUNNER_TOKEN=<registration token from Settings -> Actions -> Runners>}"

command -v docker >/dev/null || { echo "!! docker is required (deploy.sh drives compose)"; exit 3; }
command -v rsync  >/dev/null || { echo "!! rsync is required"; exit 3; }

if [ -d "$RUNNER_DIR" ] && [ -f "$RUNNER_DIR/.runner" ]; then
  echo "!! $RUNNER_DIR already holds a configured runner. Remove it first:"
  echo "     cd $RUNNER_DIR && ./svc.sh stop && ./svc.sh uninstall && ./config.sh remove --token <token>"
  exit 4
fi

VER="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
       | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -1)"
[ -n "$VER" ] || { echo "!! could not resolve the latest runner version"; exit 3; }
echo ">> installing actions-runner $VER into $RUNNER_DIR"

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"
curl -fsSL -o runner.tar.gz \
  "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-linux-x64-${VER}.tar.gz"
tar xzf runner.tar.gz && rm -f runner.tar.gz
./bin/installdependencies.sh

# --unattended so it never blocks on a prompt; --replace so a re-register after a rebuild
# does not need the old registration deleted by hand first.
#
# RUNS AS ROOT, DELIBERATELY. deploy.sh drives `docker compose`, which reads
# /opt/kssl/app/.env (root:root 600), and writes /opt/kssl/app. That is exactly what the
# ssh path already did as root@, so running as root is behaviour PARITY, not an
# escalation. And membership of the `docker` group is root-equivalent anyway -- a user
# who can run `docker run -v /:/host` is root with extra steps -- so a non-root runner
# would buy the appearance of least privilege and none of the substance. The real control
# is upstream: only someone who can push to a protected branch can make this run.
RUNNER_ALLOW_RUNASROOT=1 ./config.sh \
  --url "$REPO_URL" \
  --token "$RUNNER_TOKEN" \
  --name "kssl-$LABEL" \
  --labels "self-hosted,$LABEL" \
  --work "_work" \
  --unattended --replace

./svc.sh install root
./svc.sh start

# Restart-on-failure. svc.sh writes a unit with Restart=always but no backoff, so a
# runner that cannot reach GitHub restarts in a tight loop. A 10s gap makes an outage
# quiet in the journal instead of a wall of text.
UNIT="$(systemctl list-units --type=service --all --no-legend 'actions.runner.*' | awk '{print $1}' | head -1)"
if [ -n "$UNIT" ]; then
  mkdir -p "/etc/systemd/system/${UNIT}.d"
  cat > "/etc/systemd/system/${UNIT}.d/restart.conf" <<EOF
[Service]
Restart=always
RestartSec=10
EOF
  systemctl daemon-reload
  systemctl restart "$UNIT"
  echo ">> $UNIT: Restart=always, RestartSec=10"
fi

echo
echo ">> registered as 'kssl-$LABEL' with labels: self-hosted, $LABEL"
systemctl is-active "${UNIT:-actions.runner.service}" || true
echo ">> verify at $REPO_URL/settings/actions/runners  (it should read 'Idle')"
