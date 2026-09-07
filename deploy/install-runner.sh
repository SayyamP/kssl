#!/usr/bin/env bash
# Install and register a self-hosted GitHub Actions runner ON THE BOX IT DEPLOYS.
#
#   deploy/install-runner.sh <prod|staging> --prepare   # no token; everything but register
#   RUNNER_TOKEN=AXXXX... deploy/install-runner.sh <prod|staging>
#
# TWO PHASES, BECAUSE ONLY ONE OF THEM NEEDS THE TOKEN. --prepare runs the environment
# guard, installs the dependencies, downloads and unpacks the runner, and proves docker,
# the workspace and outbound connectivity work -- none of which needs a credential, and
# all of which is where an install actually goes wrong. `register` is then a few seconds
# of ./config.sh, which matters: a registration token is valid for ONE HOUR, so the less
# that happens between minting it and using it, the fewer expired-token retries.
#
# The token comes from the environment, never from a file and never from this repository:
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
LABEL="${1:?usage: install-runner.sh <prod|staging> [--prepare]}"
PREPARE_ONLY=0
[ "${2:-}" = "--prepare" ] && PREPARE_ONLY=1

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

if [ "$PREPARE_ONLY" = 0 ]; then
  : "${RUNNER_TOKEN:?set RUNNER_TOKEN=<registration token from Settings -> Actions -> Runners>}"
fi

# PREREQUISITES, CHECKED BEFORE ANYTHING IS DOWNLOADED. Each one is something a deploy
# job actually does, so a missing one is a deploy that fails halfway rather than an
# install that fails cleanly.
fail=0
for c in docker rsync git curl tar; do
  if command -v "$c" >/dev/null; then echo "   ok   $c $(command -v "$c")"
  else echo "   !!   $c MISSING"; fail=1; fi
done
# The deploy runs `docker compose`, not just `docker` -- v1 and the v2 plugin are
# different things and only one of them answers this.
if docker compose version >/dev/null 2>&1; then echo "   ok   docker compose: $(docker compose version --short)"
else echo "   !!   'docker compose' (v2 plugin) MISSING -- deploy.sh drives it"; fail=1; fi
# Reading /opt/kssl/app/.env is what forces this to run as root; prove it now rather
# than discovering it when compose cannot interpolate the file.
if [ -r /opt/kssl/app/.env ]; then echo "   ok   /opt/kssl/app/.env readable"
else echo "   !!   /opt/kssl/app/.env NOT readable -- compose cannot interpolate it"; fail=1; fi
if [ -w /opt/kssl/app ]; then echo "   ok   /opt/kssl/app writable (the rsync target)"
else echo "   !!   /opt/kssl/app NOT writable -- the local rsync step would fail"; fail=1; fi
# Outbound only. The runner long-polls GitHub on 443; nothing listens for it.
for u in https://api.github.com https://ghcr.io; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$u" || echo 000)
  if [ "$code" != "000" ]; then echo "   ok   outbound $u -> HTTP $code"
  else echo "   !!   outbound $u UNREACHABLE"; fail=1; fi
done
[ "$fail" = 0 ] || { echo "!! prerequisites failed; fix the above before registering"; exit 3; }

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

# The workspace the checkout and the local rsync will use. Created here so a permission
# problem surfaces now, under a command someone is watching, and not inside a deploy.
mkdir -p "$RUNNER_DIR/_work"
touch "$RUNNER_DIR/_work/.writable" && rm -f "$RUNNER_DIR/_work/.writable"
echo ">> workspace $RUNNER_DIR/_work is writable"

if [ "$PREPARE_ONLY" = 1 ]; then
  echo
  echo ">> PREPARED, NOT REGISTERED. Nothing is running and no service was installed."
  echo "   Runner $VER is unpacked in $RUNNER_DIR and every prerequisite above passed."
  echo "   To finish, with a token minted in the last hour:"
  echo "     RUNNER_TOKEN=<token> $0 $LABEL"
  exit 0
fi

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

# THE DROP-IN IS WRITTEN BEFORE THE FIRST START, AND IT CARRIES TWO THINGS THE SHIPPED
# UNIT DOES NOT HAVE. Both were found by reading bin/actions.runner.service.template on a
# prepared box rather than by assuming.
#
#   Restart / RestartSec -- the template has NO Restart= line at all. It carries
#   KillMode, KillSignal and TimeoutStopSec and nothing else, so a runner whose process
#   dies stays dead until someone notices, and the environment it serves queues its next
#   deploy for 24 hours. RestartSec=10 keeps an outage quiet in the journal instead of a
#   tight loop.
#
#   RUNNER_ALLOW_RUNASROOT -- run-helper.sh.template line 5 refuses to start as root
#   without it (`if [ $user_id -eq 0 -a -z "$RUNNER_ALLOW_RUNASROOT" ]`), and the
#   generated unit sets no Environment= and no EnvironmentFile. Exporting it for
#   config.sh alone is not enough: that shell is gone by the time systemd starts the
#   service. Setting it here is harmless if the service path happens not to consult the
#   helper, and is the difference between a working runner and one that will not start
#   if it does.
UNIT="$(systemctl list-units --type=service --all --no-legend 'actions.runner.*' | awk '{print $1}' | head -1)"
[ -n "$UNIT" ] || { echo "!! svc.sh install did not create a unit"; exit 6; }
mkdir -p "/etc/systemd/system/${UNIT}.d"
cat > "/etc/systemd/system/${UNIT}.d/override.conf" <<EOF
[Service]
Restart=always
RestartSec=10
Environment=RUNNER_ALLOW_RUNASROOT=1
EOF
systemctl daemon-reload
./svc.sh start
echo ">> $UNIT: Restart=always, RestartSec=10, RUNNER_ALLOW_RUNASROOT=1"

# "It started" and "it comes back after a reboot" are different claims. svc.sh enables
# the unit (the template carries WantedBy=multi-user.target), but check it rather than
# trust it -- a runner that does not survive a reboot is the 2026-09-07 VPS-A outage
# turned into a deploy outage.
systemctl is-enabled "$UNIT" >/dev/null 2>&1 \
  && echo ">> $UNIT is enabled (survives reboot)" \
  || { echo "!! $UNIT is NOT enabled; it will not come back after a reboot"; exit 7; }

echo
echo ">> registered as 'kssl-$LABEL' with labels: self-hosted, $LABEL"
systemctl is-active "${UNIT:-actions.runner.service}" || true
echo ">> verify at $REPO_URL/settings/actions/runners  (it should read 'Idle')"
