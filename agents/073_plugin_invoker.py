#!/usr/bin/env python3
"""Agent 073 — Plugin Invoker
Role: Handles plugin invocations via the broker's plugin bridge.
Listens for: invoke <plugin_name> <skill_name> [args_json], invoke_async <plugin_name> <skill_name>, plugin_results
Emits: plugin invocation results
"""
import os, sys, json, time
from collections import deque
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_073_plugin_invoker"
AGENT_NAME = "Agent 073 — Plugin Invoker"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Track results: deque of {ts, plugin, skill, status, result, duration_ms}
_results = deque(maxlen=100)
_invoke_counter = 0


def api(path, method="GET", data=None):
    url = f"{BROKER}{path}"
    try:
        if method == "GET":
            return requests.get(url, headers=HEADERS, timeout=5).json()
        return requests.post(url, json=data, headers=HEADERS, timeout=5).json()
    except Exception as e:
        print(f"[{AGENT_ID}] api error: {e}")
        return {}


def send(to, text):
    api("/api/send", "POST", {"to": to, "from": AGENT_ID, "text": text, "room": ROOM})


def _invoke_plugin(plugin_name, skill_name, args=None, wait_for_result=True, timeout=10.0):
    """POST a plugin_invoke message via broker. Returns (ok, result_data)."""
    global _invoke_counter
    _invoke_counter += 1
    request_id = f"invoke_{_invoke_counter}_{int(time.time())}"
    payload = {
        "type": "plugin_invoke",
        "request_id": request_id,
        "plugin": plugin_name,
        "tool": skill_name,
        "args": args or {},
    }
    t0 = time.time()
    headers = {"Content-Type": "application/json"}
    headers.update(HEADERS)
    try:
        r = requests.post(
            f"{BROKER}/api/plugin_invoke",
            json=payload,
            headers=headers,
            timeout=timeout
        )
        duration_ms = round((time.time() - t0) * 1000, 2)
        if r.status_code in (200, 202):
            data = r.json()
            result = {
                "ts": time.time(),
                "plugin": plugin_name,
                "skill": skill_name,
                "request_id": request_id,
                "status": data.get("status", "ok"),
                "result": data,
                "duration_ms": duration_ms,
            }
            _results.appendleft(result)
            return True, data
        else:
            err = {"error": f"HTTP {r.status_code}", "body": r.text[:200]}
            _results.appendleft({
                "ts": time.time(),
                "plugin": plugin_name,
                "skill": skill_name,
                "request_id": request_id,
                "status": "error",
                "result": err,
                "duration_ms": duration_ms,
            })
            return False, err
    except Exception as e:
        duration_ms = round((time.time() - t0) * 1000, 2)
        err = {"error": str(e)}
        _results.appendleft({
            "ts": time.time(),
            "plugin": plugin_name,
            "skill": skill_name,
            "request_id": request_id,
            "status": "error",
            "result": err,
            "duration_ms": duration_ms,
        })
        return False, err


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    # Handle plugin_invoke_result events forwarded as messages
    if msg.get("type") == "plugin_invoke_result":
        result = {
            "ts": time.time(),
            "plugin": msg.get("plugin", "?"),
            "skill": msg.get("tool", "?"),
            "request_id": msg.get("request_id", ""),
            "status": msg.get("status", "?"),
            "result": msg,
            "duration_ms": 0,
        }
        _results.appendleft(result)
        return

    if text.startswith("invoke "):
        # invoke <plugin_name> <skill_name> [args_json]
        parts = text[len("invoke "):].split(None, 2)
        if len(parts) < 2:
            send(sender, "usage: invoke <plugin_name> <skill_name> [args_json]")
            return
        plugin_name = parts[0]
        skill_name = parts[1]
        args = {}
        if len(parts) == 3:
            try:
                args = json.loads(parts[2])
            except json.JSONDecodeError as e:
                send(sender, f"invalid args_json: {e}")
                return
        ok, result = _invoke_plugin(plugin_name, skill_name, args)
        if ok:
            send(sender, json.dumps({
                "status": "invoked",
                "plugin": plugin_name,
                "skill": skill_name,
                "result": result,
            }))
        else:
            send(sender, json.dumps({"status": "error", "error": result}))

    elif text.startswith("invoke_async "):
        parts = text[len("invoke_async "):].split(None, 1)
        if len(parts) < 2:
            send(sender, "usage: invoke_async <plugin_name> <skill_name>")
            return
        plugin_name = parts[0]
        skill_name = parts[1]
        # Fire and forget — don't wait for result
        import threading
        t = threading.Thread(
            target=_invoke_plugin,
            args=(plugin_name, skill_name),
            kwargs={"wait_for_result": False},
            daemon=True,
        )
        t.start()
        send(sender, f"async invocation fired: {plugin_name}/{skill_name}")

    elif text == "plugin_results":
        recent = list(_results)[:10]
        send(sender, json.dumps({
            "count": len(recent),
            "results": [
                {
                    "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["ts"])),
                    "plugin": r["plugin"],
                    "skill": r["skill"],
                    "status": r["status"],
                    "duration_ms": r["duration_ms"],
                }
                for r in recent
            ],
        }))


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
