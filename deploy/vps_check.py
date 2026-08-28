"""Can we reach the VPS, and is it the machine the plan assumes?

    python deploy/vps_check.py

Reads .env, connects, and runs READ-ONLY commands: kernel, cores, memory, disk,
whether Docker is installed, what is already listening. It changes nothing --
deployment is a separate, deliberate step.

The password is read from .env and passed to the SSH library directly. It is never
put on a command line, never echoed, and never written to a log.
"""
import io
import os
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:                                     # pragma: no cover
    sys.exit("paramiko is not installed:  python -m pip install paramiko")

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def env(path=None):
    """The .env file as a dict. No shell, no export, no echo."""
    out = {}
    p = path or (ROOT / ".env")
    if not p.exists():
        sys.exit("no .env -- copy .env.example and fill it in")
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


CHECKS = [
    ("host", "hostname"),
    ("os", "lsb_release -ds 2>/dev/null || cat /etc/os-release | head -1"),
    ("kernel", "uname -r"),
    ("cores", "nproc"),
    ("memory", "free -h | awk '/Mem:/ {print $2\" total, \"$7\" available\"}'"),
    ("disk", "df -h / | awk 'NR==2 {print $2\" total, \"$4\" free\"}'"),
    ("cpu", "lscpu | awk -F: '/Model name/ {print $2}' | head -1"),
    ("docker", "docker --version 2>/dev/null || echo 'not installed'"),
    ("compose", "docker compose version 2>/dev/null || echo 'not installed'"),
    ("listening", "ss -ltnp 2>/dev/null | awk 'NR>1 {print $4}' | sort -u | head -12"),
    ("containers", "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | head -10"),
    ("swap", "free -h | awk '/Swap:/ {print $2\" total\"}'"),
]


def main():
    e = env()
    host = e.get("KSSL_VPS_HOST")
    user = e.get("KSSL_VPS_USER") or "root"
    port = int(e.get("KSSL_VPS_SSH_PORT") or 22)
    key = e.get("KSSL_VPS_SSH_KEY") or ""
    pw = e.get("KSSL_VPS_PASSWORD") or ""
    if not host:
        sys.exit("KSSL_VPS_HOST is empty in .env")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = {"hostname": host, "port": port, "username": user, "timeout": 20,
          "auth_timeout": 20, "banner_timeout": 20}
    if key and Path(os.path.expanduser(key)).exists():
        kw["key_filename"] = os.path.expanduser(key)
        how = "key"
    elif pw:
        kw["password"] = pw
        kw["look_for_keys"] = False
        how = "password"
    else:
        sys.exit("no KSSL_VPS_SSH_KEY path and no KSSL_VPS_PASSWORD in .env")

    print("connecting to %s@%s:%d by %s ..." % (user, host, port, how))
    try:
        cli.connect(**kw)
    except paramiko.AuthenticationException:
        sys.exit("REFUSED: the server rejected these credentials")
    except Exception as exc:                            # noqa: BLE001
        sys.exit("FAILED: %s" % exc)
    print("connected.\n")

    for label, cmd in CHECKS:
        _in, out, err = cli.exec_command(cmd, timeout=25)
        text = (out.read().decode("utf-8", "replace").strip()
                or err.read().decode("utf-8", "replace").strip() or "-")
        first, *rest = text.splitlines() or [""]
        print("  %-11s %s" % (label, first.strip()))
        for r in rest:
            print("  %-11s %s" % ("", r.strip()))
    cli.close()
    print("\nread-only check complete; nothing on the server was changed.")


if __name__ == "__main__":
    main()
