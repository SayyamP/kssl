#!/usr/bin/env bash
# Install (or remove) the hourly serving refresh on a replica. Run ON the target.
#
#   ./deploy/install_refresh_timer.sh staging
#   ./deploy/install_refresh_timer.sh staging --remove
#
# systemd, not cron, for three reasons that matter to an unattended job: it will not
# start a second run while one is still going, a missed hour is caught up once rather
# than 24 times, and the output lands in journalctl beside every other unit rather than
# in a mail spool nobody reads.
set -euo pipefail

ENVN="${1:?usage: install_refresh_timer.sh <staging|dev> [--remove]}"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$APP/deploy/envs/$ENVN.env" ] || { echo "!! no such environment: $ENVN"; exit 2; }
grep -q '^KSSL_DATA_ROLE=replica' "$APP/deploy/envs/$ENVN.env" || {
  echo "!! $ENVN is not a replica -- refusing to install a timer that overwrites its data"; exit 3; }

U="kssl-refresh-serving@$ENVN"
if [ "${2:-}" = "--remove" ]; then
  systemctl disable --now "$U.timer" 2>/dev/null || true
  rm -f /etc/systemd/system/kssl-refresh-serving@.{service,timer}
  systemctl daemon-reload
  echo ">> removed $U.timer"
  exit 0
fi

install -m644 "$APP/deploy/systemd/kssl-refresh-serving.service" /etc/systemd/system/kssl-refresh-serving@.service
install -m644 "$APP/deploy/systemd/kssl-refresh-serving.timer"   /etc/systemd/system/kssl-refresh-serving@.timer
systemctl daemon-reload
systemctl enable --now "$U.timer"
echo ">> installed $U.timer"
systemctl list-timers "$U.timer" --no-pager | head -3
echo
echo "   logs:      journalctl -u $U.service -f"
echo "   run now:   systemctl start $U.service"
echo "   stop it:   $0 $ENVN --remove"
