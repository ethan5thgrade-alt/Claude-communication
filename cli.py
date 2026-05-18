"""Agent Mesh terminal CLI — talks to the broker over REST."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8765"


def _pp(obj):
    print(json.dumps(obj, indent=2, default=str))


def _get(path: str, raw: bool = False):
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            data = r.read()
            if raw:
                return data.decode("utf-8", errors="replace")
            return json.loads(data)
    except urllib.error.URLError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, body: dict):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
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
  python cli.py health
  python cli.py metrics
  python cli.py instances
  python cli.py tasks
  python cli.py memory
  python cli.py task "<title>" [--assignee <id>] [--priority <p>]
  python cli.py memorize <key> "<value>" [--type <mem_type>]
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
            if key in names and i + 1 < len(args):
                flags[key] = args[i + 1]
                i += 2
                continue
        pos.append(a)
        i += 1
    return pos, flags


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
        key = pos[0]
        value = pos[1]
        body = {
            "key": key,
            "value": value,
            "mem_type": flags.get("type", "contract"),
        }
        _pp(_post("/api/memory", body))
    else:
        print(USAGE)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
