#!/usr/bin/env python3
"""Agent 031 — Memory Manager
Role: Coordinates all memory operations, enforces memory schema.
Listens for: memory_overview, memory_health
Emits: memory stats every 5min
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_031_memory_manager"
AGENT_NAME = "Agent 031 — Memory Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 300  # 5 minutes
STALE_DAYS = 7
VALID_TYPES = {"fact", "decision", "context", "contract", "preference", "warning"}
MAX_VALUE_LEN = 4000


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


def get_memory():
    result = api("/api/memory")
    if isinstance(result, list):
        return result
    return result.get("memory", []) if isinstance(result, dict) else []


def run_cycle():
    entries = get_memory()
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_threshold = now - datetime.timedelta(days=STALE_DAYS)

    counts_by_type = {}
    stale_count = 0
    for entry in entries:
        t = entry.get("type", "unknown")
        counts_by_type[t] = counts_by_type.get(t, 0) + 1
        # Check staleness via timestamp in entry
        ts_str = entry.get("ts") or entry.get("updated_at") or ""
        if ts_str:
            try:
                ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < stale_threshold:
                    stale_count += 1
            except Exception:
                pass

    stats = {
        "total": len(entries),
        "by_type": counts_by_type,
        "stale_count": stale_count,
    }
    broadcast(f"[memory_manager] Memory stats: {json.dumps(stats)}")
    print(f"[{AGENT_ID}] cycle: {stats}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "memory_overview":
        entries = get_memory()
        counts = {}
        oldest = None
        newest = None
        for entry in entries:
            t = entry.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
            ts_str = entry.get("ts") or entry.get("created_at") or ""
            if ts_str:
                if oldest is None or ts_str < oldest:
                    oldest = ts_str
                if newest is None or ts_str > newest:
                    newest = ts_str
        send(sender, json.dumps({
            "total": len(entries),
            "by_type": counts,
            "oldest": oldest,
            "newest": newest,
        }))

    elif text == "memory_health":
        entries = get_memory()
        issues = []
        for entry in entries:
            key = entry.get("key", "")
            val = entry.get("value")
            t = entry.get("type", "")
            if val is None or val == "":
                issues.append({"key": key, "issue": "null or empty value"})
            if t not in VALID_TYPES:
                issues.append({"key": key, "issue": f"invalid type '{t}'"})
            val_str = str(val) if val is not None else ""
            if len(val_str) > MAX_VALUE_LEN:
                issues.append({"key": key, "issue": f"oversized value ({len(val_str)} chars)"})
        send(sender, json.dumps({"issues": issues, "issue_count": len(issues)}))


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
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
