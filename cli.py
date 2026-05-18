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
MESH_TOKEN = os.environ.get("MESH_TOKEN") or None


def _auth_headers() -> dict:
    h = {}
    if MESH_TOKEN:
        h["X-Mesh-Token"] = MESH_TOKEN
    return h


def _pp(obj):
    print(json.dumps(obj, indent=2, default=str))


def _get(path: str):
    req = urllib.request.Request(BASE + path, headers=_auth_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
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
  python cli.py send <to> "<text>"
  python cli.py status
  python cli.py state
  python cli.py clear
  python cli.py discover
"""


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
        to = argv[2]
        text = argv[3]
        _pp(_post("/api/send", {"to": to, "text": text}))
    elif cmd == "status":
        _pp(_get("/api/status"))
    elif cmd == "state":
        _pp(_get("/api/state"))
    elif cmd == "clear":
        _pp(_post("/api/clear", {}))
    elif cmd == "discover":
        return _discover()
    else:
        print(USAGE)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
