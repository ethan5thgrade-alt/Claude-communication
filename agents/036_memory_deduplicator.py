#!/usr/bin/env python3
"""Agent 036 — Memory Deduplicator
Role: Finds and merges duplicate or conflicting memory entries.
Listens for: find_duplicates, resolve_conflict <key> <winning_value>, dedup_report
Emits: dedup findings
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_036_memory_deduplicator"
AGENT_NAME = "Agent 036 — Memory Deduplicator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 3600  # 1 hour

_dedup_stats = {"found": 0, "resolved": 0}


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


def get_memory():
    result = api("/api/memory")
    if isinstance(result, list):
        return result
    return result.get("memory", []) if isinstance(result, dict) else []


def find_conflicts(entries):
    """Find keys with multiple entries where values differ."""
    # Group by lowercase key
    key_groups = {}
    for entry in entries:
        k = entry.get("key", "").lower()
        if k not in key_groups:
            key_groups[k] = []
        key_groups[k].append(entry)

    conflicts = []
    for k, group in key_groups.items():
        if len(group) > 1:
            values = list({str(e.get("value", "")) for e in group})
            if len(values) > 1:
                conflicts.append({
                    "key": k,
                    "count": len(group),
                    "values": values[:3],  # show up to 3 conflicting values
                    "agents": [e.get("by", "?") for e in group],
                })
    return conflicts


def run_cycle():
    entries = get_memory()
    conflicts = find_conflicts(entries)
    _dedup_stats["found"] = len(conflicts)
    if conflicts:
        print(f"[{AGENT_ID}] found {len(conflicts)} duplicate/conflicting keys")
    else:
        print(f"[{AGENT_ID}] no duplicates found")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "find_duplicates":
        entries = get_memory()
        conflicts = find_conflicts(entries)
        if conflicts:
            send(sender, json.dumps({"conflicts": conflicts, "count": len(conflicts)}))
        else:
            send(sender, "no duplicate or conflicting memory entries found")

    elif text.startswith("resolve_conflict "):
        rest = text[len("resolve_conflict "):].strip()
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            send(sender, "usage: resolve_conflict <key> <winning_value>")
            return
        key, winning_value = parts[0], parts[1]

        # Write the authoritative value
        result = api("/api/memory", "POST", {
            "key": key,
            "value": winning_value,
            "mem_type": "fact",
        })
        _dedup_stats["resolved"] += 1

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        print(f"[{AGENT_ID}] resolved conflict for key '{key}' at {now_str}")
        send(sender, f"conflict resolved: key='{key}' authoritative value written")

    elif text == "dedup_report":
        entries = get_memory()
        conflicts = find_conflicts(entries)
        send(sender, json.dumps({
            "current_conflicts": len(conflicts),
            "total_found_this_session": _dedup_stats["found"],
            "total_resolved_this_session": _dedup_stats["resolved"],
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
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
