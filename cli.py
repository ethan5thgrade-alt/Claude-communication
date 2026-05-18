"""Agent Mesh terminal CLI — talks to the broker over REST."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8765"


def _pp(obj):
    print(json.dumps(obj, indent=2, default=str))


def _get(path: str):
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            return json.loads(r.read())
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
"""


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
    else:
        print(USAGE)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
