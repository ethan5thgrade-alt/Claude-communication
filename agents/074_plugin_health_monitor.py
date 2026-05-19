#!/usr/bin/env python3
"""Agent 074 — Plugin Health Monitor
Role: Monitors plugin availability and response times.
Listens for: plugin_health, plugin_uptime <name>
Emits: plugin health status alerts
"""
import os, sys, json, time
from collections import defaultdict, deque
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_074_plugin_health_monitor"
AGENT_NAME = "Agent 074 — Plugin Health Monitor"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Per-plugin health records: {name: deque of {ts, ok, response_ms}}
_health_history = defaultdict(lambda: deque(maxlen=100))
# Last known status per plugin: {name: "healthy"|"degraded"|"offline"}
_last_status = {}


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


def broadcast(text):
    send("all", text)


def _test_plugin(name):
    """Attempt a safe test invocation of a plugin. Returns (ok, response_ms)."""
    url = f"{BROKER}/api/plugins/{name}"
    t0 = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        response_ms = round((time.time() - t0) * 1000, 2)
        ok = r.status_code == 200
        return ok, response_ms
    except Exception:
        response_ms = round((time.time() - t0) * 1000, 2)
        return False, response_ms


def _compute_status(name):
    """Compute health status from history."""
    history = list(_health_history.get(name, []))
    if not history:
        return "unknown"
    recent = history[-10:]
    ok_count = sum(1 for h in recent if h["ok"])
    ratio = ok_count / len(recent)
    if ratio >= 0.9:
        return "healthy"
    elif ratio >= 0.5:
        return "degraded"
    return "offline"


def run_cycle():
    result = api("/api/plugins")
    plugins = result.get("plugins", []) if isinstance(result, dict) else []

    for plugin in plugins:
        name = plugin.get("name", "")
        if not name:
            continue
        ok, response_ms = _test_plugin(name)
        ts = time.time()
        _health_history[name].appendleft({"ts": ts, "ok": ok, "response_ms": response_ms})

        new_status = _compute_status(name)
        old_status = _last_status.get(name)
        if old_status and old_status != new_status:
            broadcast(f"[plugin_health] plugin '{name}' status changed: {old_status} -> {new_status}")
        _last_status[name] = new_status

    print(f"[{AGENT_ID}] checked {len(plugins)} plugins")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "plugin_health":
        health = {}
        for name, status in _last_status.items():
            history = list(_health_history.get(name, []))
            recent = history[:10]
            ok_count = sum(1 for h in recent if h["ok"])
            resp_times = [h["response_ms"] for h in recent if h["ok"]]
            avg_resp = round(sum(resp_times) / len(resp_times), 2) if resp_times else 0
            health[name] = {
                "status": status,
                "checks": len(recent),
                "ok_count": ok_count,
                "avg_response_ms": avg_resp,
            }
        send(sender, json.dumps({"plugin_health": health, "count": len(health)}))

    elif text.startswith("plugin_uptime "):
        name = text[len("plugin_uptime "):].strip()
        history = list(_health_history.get(name, []))
        if not history:
            send(sender, f"no health data for plugin '{name}' — not found or not yet checked")
            return
        total = len(history)
        ok_count = sum(1 for h in history if h["ok"])
        uptime_pct = round(ok_count / total * 100, 1)
        resp_times = [h["response_ms"] for h in history if h["ok"]]
        avg_resp = round(sum(resp_times) / len(resp_times), 2) if resp_times else 0
        first_ts = history[-1]["ts"] if history else time.time()
        send(sender, json.dumps({
            "plugin": name,
            "status": _last_status.get(name, "unknown"),
            "uptime_pct": uptime_pct,
            "total_checks": total,
            "ok_checks": ok_count,
            "avg_response_ms": avg_resp,
            "monitoring_since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(first_ts)),
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
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
