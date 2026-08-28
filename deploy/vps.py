"""Run a command on the VPS over SSH, or copy a file to it.

    python deploy/vps.py  "uptime"
    python deploy/vps.py  --put local/path  /remote/path
    python deploy/vps.py  --get /remote/path  local/path
    python deploy/vps.py  --forward 11500 11434   # local -> VPS port, until ^C

Credentials come from .env (gitignored) and are handed straight to paramiko.
They are never put on a command line, never echoed, never logged. Everything
this prints is the remote command's own output.
"""
import io
import os
import select
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


def connect():
    e = env()
    host = e.get("KSSL_VPS_HOST")
    if not host:
        sys.exit("KSSL_VPS_HOST is empty in .env")
    user = e.get("KSSL_VPS_USER") or "root"
    port = int(e.get("KSSL_VPS_SSH_PORT") or 22)
    key = e.get("KSSL_VPS_SSH_KEY") or ""
    pw = e.get("KSSL_VPS_PASSWORD") or ""

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = {"hostname": host, "port": port, "username": user, "timeout": 30,
          "auth_timeout": 30, "banner_timeout": 30}
    if key and Path(os.path.expanduser(key)).exists():
        kw["key_filename"] = os.path.expanduser(key)
    elif pw:
        kw["password"] = pw
        kw["look_for_keys"] = False
    else:
        sys.exit("no KSSL_VPS_SSH_KEY path and no KSSL_VPS_PASSWORD in .env")
    cli.connect(**kw)
    return cli


def run(cli, cmd, timeout=1800):
    """Stream a remote command. Returns its exit status."""
    chan = cli.get_transport().open_session()
    chan.settimeout(timeout)
    chan.get_pty()                  # so long jobs still flush line by line
    chan.exec_command(cmd)
    buf = b""
    # select(), not a spin: the previous loop polled recv_ready() with no wait,
    # pinned a core for the length of every remote command, and -- because it
    # never blocked on the socket -- could never hit chan.settimeout either.
    while True:
        r, _, _ = select.select([chan], [], [], 0.5)
        if r and chan.recv_ready():
            data = chan.recv(65536)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                print(line.decode("utf-8", "replace").rstrip())
                sys.stdout.flush()
        elif chan.exit_status_ready():
            # drain whatever is still buffered before leaving, or the tail of
            # the output is silently lost
            while chan.recv_ready():
                chunk = chan.recv(65536)
                if not chunk:
                    break
                buf += chunk
            break
    if buf:
        print(buf.decode("utf-8", "replace").rstrip())
    return chan.recv_exit_status()



def forward(cli, local_port, remote_port, remote_host="127.0.0.1"):
    """Publish a VPS loopback port on this machine, until interrupted.

    The database and the LLM are both bound to loopback on the VPS on purpose,
    so this is how the pipeline reaches them: the port never leaves that host,
    it only appears here for the length of this process.
    """
    import select
    import socketserver
    import threading

    transport = cli.get_transport()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                chan = transport.open_channel(
                    "direct-tcpip", (remote_host, remote_port),
                    self.request.getpeername())
            except Exception as exc:                    # noqa: BLE001
                print("forward refused: %s" % exc, file=sys.stderr)
                return
            if chan is None:
                return
            try:
                while True:
                    r, _, _ = select.select([self.request, chan], [], [], 1)
                    if self.request in r:
                        data = self.request.recv(65536)
                        if not data:
                            break
                        chan.sendall(data)
                    if chan in r:
                        data = chan.recv(65536)
                        if not data:
                            break
                        self.request.sendall(data)
            finally:
                chan.close()
                self.request.close()

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    srv = Server(("127.0.0.1", local_port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print("forwarding 127.0.0.1:%d -> vps:%d  (ctrl-c to stop)"
          % (local_port, remote_port))
    sys.stdout.flush()
    try:
        while True:
            t.join(1)
    except KeyboardInterrupt:
        print("closing forward")
    finally:
        srv.shutdown()
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cli = connect()
    try:
        if args[0] == "--put":
            # sftp, in chunks. An earlier version shipped the file as one base64
            # blob on the command line; that works for a script and resets the
            # connection for anything approaching a megabyte.
            run(cli, "mkdir -p $(dirname %s)" % args[2])
            sftp = cli.open_sftp()
            sftp.put(args[1], args[2])
            sftp.close()
            print("put %s -> %s (%d bytes)"
                  % (args[1], args[2], os.path.getsize(args[1])))
            return 0
        if args[0] == "--forward":
            return forward(cli, int(args[1]), int(args[2]))
        if args[0] == "--get":
            sftp = cli.open_sftp()
            sftp.get(args[1], args[2])
            sftp.close()
            print("get %s -> %s" % (args[1], args[2]))
            return 0
        return run(cli, " ".join(args))
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
