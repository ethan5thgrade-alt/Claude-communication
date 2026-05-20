#!/usr/bin/env python3
"""Agent 033 — Memory Reader
Role: Retrieves memory entries with smart search.
Listens for: recall <key>, recall_like <pattern>, recall_type <type>, recall_recent <n>
Emits: memory lookup results
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_033_memory_reader"
AGENT_NAME = "Agent 033 — Memory Reader"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}


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


def fuzzy_score(pattern, entry):
    """Simple relevance score: count matching words in key+value."""
    pattern_lower = pattern.lower()
    key_lower = str(entry.get("key", "")).lower()
    val_lower = str(entry.get("value", "")).lower()
    score = 0
    for word in pattern_lower.split():
        if word in key_lower:
            score += 2
        if word in val_lower:
            score += 1
    return score


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("recall "):
        key = text.split(" ", 1)[1].strip()
        entries = get_memory()
        match = next((e for e in entries if e.get("key") == key), None)
        if match:
            send(sender, json.dumps({
                "key": match.get("key"),
                "value": match.get("value"),
                "type": match.get("type"),
                "by": match.get("by"),
                "ts": match.get("ts"),
            }))
        else:
            send(sender, f"no memory found for key '{key}'")

    elif text.startswith("recall_like "):
        pattern = text.split(" ", 1)[1].strip()
        entries = get_memory()
        scored = [(fuzzy_score(pattern, e), e) for e in entries]
        scored = [(s, e) for s, e in scored if s > 0]
        scored.sort(key=lambda x: -x[0])
        top5 = [e for _, e in scored[:5]]
        if top5:
            results = [{"key": e.get("key"), "value": str(e.get("value", ""))[:200], "type": e.get("type")} for e in top5]
            send(sender, json.dumps(results))
        else:
            send(sender, f"no memory matches pattern '{pattern}'")

    elif text.startswith("recall_type "):
        mem_type = text.split(" ", 1)[1].strip()
        entries = get_memory()
        matches = [e for e in entries if e.get("type") == mem_type]
        results = [{"key": e.get("key"), "value": str(e.get("value", ""))[:200]} for e in matches]
        send(sender, json.dumps({"type": mem_type, "count": len(results), "entries": results}))

    elif text.startswith("recall_recent "):
        n_str = text.split(" ", 1)[1].strip()
        try:
            n = int(n_str)
        except ValueError:
            send(sender, "error: n must be an integer")
            return
        entries = get_memory()
        # Sort by ts descending
        def ts_sort(e):
            return e.get("ts") or e.get("created_at") or ""
        sorted_entries = sorted(entries, key=ts_sort, reverse=True)
        recent = sorted_entries[:n]
        results = [{"key": e.get("key"), "value": str(e.get("value", ""))[:200], "type": e.get("type"), "ts": e.get("ts")} for e in recent]
        send(sender, json.dumps(results))


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
