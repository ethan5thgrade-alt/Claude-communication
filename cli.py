"""Agent Mesh terminal CLI — talks to the broker over REST."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8765"
MDNS_SERVICE_TYPE = "_agent-mesh._tcp.local."


def _load_token() -> str | None:
    """MESH_TOKEN env var, then ~/.agent-mesh-token (written by the `token`
    subcommand), then the MESH_TOKEN= line in ~/.agent-mesh/session.env."""
    tok = os.environ.get("MESH_TOKEN")
    if tok:
        return tok
    try:
        with open(os.path.expanduser("~/.agent-mesh-token")) as f:
            tok = f.read().strip()
        if tok:
            return tok
    except OSError:
        pass
    try:
        with open(os.path.expanduser("~/.agent-mesh/session.env")) as f:
            for line in f:
                if line.startswith("MESH_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
                    if tok:
                        return tok
    except OSError:
        pass
    return None


MESH_TOKEN = _load_token()


def _auth_headers() -> dict:
    h = {}
    if MESH_TOKEN:
        h["X-Mesh-Token"] = MESH_TOKEN
    return h


def _pp(obj):
    print(json.dumps(obj, indent=2, default=str))


def _get(path: str, raw: bool = False):
    req = urllib.request.Request(BASE + path, headers=_auth_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read()
            if raw:
                return data.decode("utf-8", errors="replace")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": str(e)}
    except urllib.error.URLError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, body: dict):
    headers = {"Content-Type": "application/json"}
    headers.update(_auth_headers())
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


USAGE = """\
Usage:
  python cli.py send <to> "<text>" [--from <sender>]   # sender defaults to $INSTANCE_ID or "you"
  python cli.py status
  python cli.py state
  python cli.py clear
  python cli.py discover
  python cli.py health
  python cli.py metrics
  python cli.py instances
  python cli.py tasks
  python cli.py memory
  python cli.py approvals
  python cli.py votes
  python cli.py flows
  python cli.py audit [--limit N]
  python cli.py messages [--limit N]
  python cli.py task "<title>" [--assignee <id>] [--priority <p>]
  python cli.py memorize <key> "<value>" [--type <mem_type>]
  python cli.py token                              # generate + persist ~/.agent-mesh-token
"""


def _parse_flags(args, names):
    """Extract --flag value pairs from args; return (positional, flags_dict)."""
    pos = []
    flags = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if "=" in key:
                key, _, val = key.partition("=")
                if key in names:
                    flags[key] = val
                    i += 1
                    continue
            elif key in names and i + 1 < len(args):
                flags[key] = args[i + 1]
                i += 2
                continue
        pos.append(a)
        i += 1
    return pos, flags


def _discover(timeout: float = 3.0) -> int:
    """Browse mDNS for `_agent-mesh._tcp.local.` brokers and print them."""
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except Exception as e:
        print(f"zeroconf not installed; install with: "
              f"python3 -m pip install --user zeroconf  ({e})")
        return 1

    found: dict[str, tuple[str, int]] = {}

    class _Listener(ServiceListener):
        def add_service(self, zc, type_, name):  # noqa: N802 (zeroconf API)
            try:
                info = zc.get_service_info(type_, name, timeout=1500)
            except Exception:
                info = None
            if not info:
                return
            host = None
            try:
                addrs = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
                if addrs:
                    host = addrs[0]
            except Exception:
                host = None
            if not host:
                try:
                    raw = info.addresses[0] if info.addresses else b""
                    host = socket.inet_ntoa(raw) if len(raw) == 4 else None
                except Exception:
                    host = None
            if not host and getattr(info, "server", None):
                host = str(info.server).rstrip(".")
            port = int(info.port) if info.port else 0
            label = name
            if label.endswith("." + MDNS_SERVICE_TYPE):
                label = label[: -(len(MDNS_SERVICE_TYPE) + 1)]
            found[name] = (host or "?", port)
            print(f"{label}  {host}:{port}")

        def update_service(self, zc, type_, name):  # noqa: N802
            pass

        def remove_service(self, zc, type_, name):  # noqa: N802
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, MDNS_SERVICE_TYPE, _Listener())
        time.sleep(timeout)
    finally:
        try:
            zc.close()
        except Exception:
            pass

    if not found:
        # Stay exit-0 per spec; print a hint to stderr so scripts can still
        # rely on exit code, while interactive users see why.
        print("(no brokers found)", file=sys.stderr)
    return 0


def main(argv):
    if len(argv) < 2:
        print(USAGE)
        return 1
    cmd = argv[1]
    if cmd == "send":
        if len(argv) < 4:
            print(USAGE)
            return 1
        # `cli.py send <to> "<text>" [--from <sender>]`
        # If --from is omitted but $INSTANCE_ID is set in env, use that as
        # the sender — lets a Claude Code session do `cli.py send cc2 "hi"`
        # and have the message attributed to cc1 (this session) instead of "you".
        pos, flags = _parse_flags(argv[2:], {"from"})
        if len(pos) < 2:
            print(USAGE)
            return 1
        to = pos[0]
        text = pos[1]
        sender = flags.get("from") or os.environ.get("INSTANCE_ID") or "you"
        body = {"to": to, "text": text}
        if sender and sender != "you":
            body["from"] = sender
        _pp(_post("/api/send", body))
    elif cmd == "status":
        _pp(_get("/api/status"))
    elif cmd == "state":
        _pp(_get("/api/state"))
    elif cmd == "clear":
        _pp(_post("/api/clear", {}))
    elif cmd == "discover":
        return _discover()
    elif cmd == "health":
        _pp(_get("/api/health"))
    elif cmd == "metrics":
        # metrics endpoint returns Prometheus text — print raw
        print(_get("/api/metrics", raw=True))
    elif cmd == "instances":
        _pp(_get("/api/instances"))
    elif cmd == "tasks":
        _pp(_get("/api/tasks"))
    elif cmd == "memory":
        _pp(_get("/api/memory"))
    elif cmd == "task":
        if len(argv) < 3:
            print(USAGE)
            return 1
        pos, flags = _parse_flags(argv[2:], {"assignee", "priority"})
        if not pos:
            print(USAGE)
            return 1
        title = pos[0]
        body = {
            "title": title,
            "assignee": flags.get("assignee", ""),
            "priority": flags.get("priority", "normal"),
            "deps": [],
        }
        _pp(_post("/api/task", body))
    elif cmd == "memorize":
        if len(argv) < 4:
            print(USAGE)
            return 1
        pos, flags = _parse_flags(argv[2:], {"type"})
        if len(pos) < 2:
            print(USAGE)
            return 1
        body = {
            "key": pos[0],
            "value": pos[1],
            "mem_type": flags.get("type", "contract"),
        }
        _pp(_post("/api/memory", body))
    elif cmd == "approvals":
        _pp(_get("/api/approvals"))
    elif cmd == "votes":
        _pp(_get("/api/votes"))
    elif cmd == "flows":
        _pp(_get("/api/flows"))
    elif cmd == "audit":
        _, flags = _parse_flags(argv[2:], {"limit"})
        path = "/api/audit"
        if flags.get("limit"):
            path += "?limit=" + flags["limit"]
        _pp(_get(path))
    elif cmd == "messages":
        _, flags = _parse_flags(argv[2:], {"limit"})
        path = "/api/messages"
        if flags.get("limit"):
            path += "?limit=" + flags["limit"]
        _pp(_get(path))
    elif cmd == "token":
        # Generate-and-persist mode. Safe to re-run; refuses to overwrite
        # an existing token unless --force is passed. Writing the token
        # does NOT change broker behavior — the broker only requires
        # X-Mesh-Token when MESH_TOKEN is set in its own env.
        import secrets, stat
        _, flags = _parse_flags(argv[2:], {"force"})
        token_path = os.path.expanduser("~/.agent-mesh-token")
        if os.path.exists(token_path) and not flags.get("force"):
            with open(token_path) as f:
                existing = f.read().strip()
            print(f"token already exists at {token_path}:")
            print(f"  {existing}")
            print("re-run with --force=1 to rotate.")
            return 0
        tok = secrets.token_urlsafe(32)
        with open(token_path, "w") as f:
            f.write(tok + "\n")
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)
        print(f"wrote {token_path}")
        print(f"  {tok}")
        print()
        print("To enforce auth on the broker, restart it with:")
        print(f"  MESH_TOKEN=$(cat {token_path}) python3 broker.py")
        print("Then set the same env var for bots and connect.py.")
    else:
        print(USAGE)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
