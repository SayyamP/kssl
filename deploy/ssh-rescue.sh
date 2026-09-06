#!/usr/bin/env bash
# LOCK-OUT RECOVERY, AND THE UNIT THAT MAKES IT UNNECESSARY NEXT TIME.
#
# Run this as root FROM THE PROVIDER'S BROWSER CONSOLE when a box has stopped
# accepting ssh. It is the only place it can be run -- that is the whole problem
# it exists to solve.
#
#   bash /opt/kssl/app/deploy/ssh-rescue.sh          # diagnose + repair + install rescue
#   bash /opt/kssl/app/deploy/ssh-rescue.sh --check  # diagnose only, change nothing
#
# WHY THE OBVIOUS ONE-LINER IS THE WRONG FIX.
#
# `systemctl restart ssh.socket` is the reflex, and on 2026-09-06 it would not have
# worked. The symptom from outside was NOT a dead port: the box accepted the TCP
# connection on 2222 in 11ms -- one round trip, so the box itself, not an edge -- and
# then closed it with no SSH banner. A dead sshd refuses the connection; a socket unit
# whose per-connection service fails ACCEPTS it and then drops it. Same "can't ssh in",
# opposite fault, and restarting the socket repairs only the first one. The usual cause
# of the second is an sshd_config that fails `sshd -t`, so that is tested first here.
#
# THE REAL DEFECT IS THAT ONE DOOR EXISTED.
#
# ssh.socket owned port 22, and a systemd .socket that cannot bind ONE of its
# ListenStreams fails the whole unit -- so a second port added for convenience became a
# way to lose the first. Every recovery path then ran through a browser console that
# only a human with a provider login can open. The rescue unit below is a plain
# sshd on its own port, not socket-activated, Restart=always: it shares no config file
# and no unit with ssh.socket, so whatever breaks one cannot reach the other.
set -uo pipefail

RESCUE_PORT="${RESCUE_PORT:-2022}"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '\n=== %s\n' "$*"; }

say "what is listening"
ss -lntp 2>/dev/null | grep -E ':(22|2222|'"$RESCUE_PORT"')\b' || echo "  nothing on 22 / 2222 / $RESCUE_PORT"

say "units"
systemctl --no-pager --failed 2>/dev/null | head
for u in ssh.socket ssh.service sshd.service; do
  systemctl is-active "$u" >/dev/null 2>&1 && echo "  active:  $u" || echo "  down:    $u ($(systemctl is-failed "$u" 2>/dev/null))"
done

say "sshd config test -- the fault a socket restart does not fix"
if sshd -t 2>/tmp/sshd_t; then
  echo "  sshd_config is valid"
  CONF_OK=1
else
  echo "  sshd_config is INVALID. This is why connections are accepted and dropped:"
  sed 's/^/    /' /tmp/sshd_t
  CONF_OK=0
fi

say "recent journal"
journalctl -u ssh.socket -u ssh@.service -u ssh.service -n 20 --no-pager 2>/dev/null | tail -20

[ "$CHECK_ONLY" = 1 ] && { echo; echo "--check: nothing changed."; exit 0; }

say "repair"
# A standalone sshd left behind by a debugging session holds a port the socket unit
# wants, and a .socket that cannot bind every ListenStream fails ENTIRELY -- taking
# port 22 down with it. That is exactly how this box was lost. Clear it first.
pkill -f 'sshd -p ' 2>/dev/null && echo "  killed a leftover standalone sshd"

if [ "$CONF_OK" = 0 ]; then
  ts=$(date +%s)
  cp -a /etc/ssh/sshd_config "/root/sshd_config.broken.$ts"
  echo "  saved the broken config to /root/sshd_config.broken.$ts"
  # Reinstall rather than guess at the edit: the packaged config is known to pass.
  DEBIAN_FRONTEND=noninteractive apt-get install -y --reinstall -o Dpkg::Options::=--force-confask openssh-server </dev/null
  sshd -t && echo "  sshd_config is valid again" || echo "  STILL invalid -- read the error above and edit /etc/ssh/sshd_config by hand"
fi

systemctl daemon-reload
systemctl reset-failed ssh.socket ssh.service ssh@.service 2>/dev/null
systemctl restart ssh.socket 2>/dev/null || systemctl restart ssh.service 2>/dev/null

say "install the rescue sshd on $RESCUE_PORT"
# Its own config file. Sharing /etc/ssh/sshd_config would mean the config error that
# takes down the main daemon takes this one down with it -- which is not a rescue.
install -d -m 755 /etc/ssh/rescue
cat > /etc/ssh/rescue/sshd_config <<EOF
Port $RESCUE_PORT
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
AuthorizedKeysFile /root/.ssh/authorized_keys
HostKey /etc/ssh/ssh_host_ed25519_key
PidFile /run/sshd-rescue.pid
LogLevel VERBOSE
EOF
/usr/sbin/sshd -t -f /etc/ssh/rescue/sshd_config || { echo "  rescue config invalid, not installing"; exit 1; }

cat > /etc/systemd/system/sshd-rescue.service <<EOF
# A SECOND DOOR, DELIBERATELY NOT SHARING ANYTHING WITH THE FIRST.
#
# Not socket-activated (a .socket that cannot bind fails whole), not reading
# /etc/ssh/sshd_config (the file most likely to be the fault), and Restart=always so a
# crash is not a lock-out. It exists so that "I broke sshd" is a one-line fix over the
# network instead of a provider console session someone has to be awake for.
[Unit]
Description=Rescue sshd on port $RESCUE_PORT, independent of ssh.socket
After=network.target

[Service]
ExecStart=/usr/sbin/sshd -D -e -f /etc/ssh/rescue/sshd_config
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sshd-rescue.service

say "result"
ss -lntp 2>/dev/null | grep -E ':(22|2222|'"$RESCUE_PORT"')\b' || echo "  STILL nothing listening -- read the journal above"
echo
echo "If port 22 listens here but times out from outside, the block is the PROVIDER"
echo "firewall, not this box -- open 22 and $RESCUE_PORT in the hPanel firewall, and set"
echo "the staging GitHub Environment's VPS_SSH_PORT to whichever one it admits."
