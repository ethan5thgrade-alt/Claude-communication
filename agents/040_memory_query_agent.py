#!/usr/bin/env python3
"""Agent 040 — Memory Query Agent
Role: Answers natural-language queries about stored memory.
Listens for: what do you know about <topic>, what was decided about <topic>, what are the contracts, forget <key>
Emits: readable memory answers, forget log entries
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_040_memory_query_agent"
AGENT_NAME = "Agent 040 — Memory Query Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

FORGET_LOG_PATH = os.path.expanduser("~/Claude-communication/forget_log.json")


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


def load_forget_log():
    try:
        with open(FORGET_LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"forgotten": []}


def save_forget_log(log):
    try:
        with open(FORGET_LOG_PATH, "w") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"[{AGENT_ID}] failed to save forget log: {e}")


def search_memory_for_topic(entries, topic, mem_type=None):
    """Return relevant memory entries for a topic."""
    topic_lower = topic.lower()
    forget_log = load_forget_log()
    forgotten_keys = {item.get("key") for item in forget_log.get("forgotten", [])}

    results = []
    for entry in entries:
        key = entry.get("key", "")
        if key in forgotten_keys:
            continue
        if mem_type and entry.get("type") != mem_type:
            continue
        key_lower = key.lower()
        val_lower = str(entry.get("value", "")).lower()
        # Check relevance
        words = topic_lower.split()
        score = sum(1 for w in words if w in key_lower or w in val_lower)
        if score > 0:
            results.append((score, entry))

    results.sort(key=lambda x: -x[0])
    return [e for _, e in results[:5]]


def format_entry(entry):
    key = entry.get("key", "?")
    value = str(entry.get("value", ""))
    mem_type = entry.get("type", "fact")
    by = entry.get("by", "?")
    return f"  [{mem_type}] {key}: {value[:200]}{'...' if len(value) > 200 else ''} (by {by})"


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    # "what do you know about <topic>"
    if text.lower().startswith("what do you know about "):
        topic = text[len("what do you know about "):].strip()
        entries = get_memory()
        matches = search_memory_for_topic(entries, topic)
        if matches:
            lines = [f"Here is what I know about '{topic}':"]
            lines.extend(format_entry(e) for e in matches)
            send(sender, "\n".join(lines))
        else:
            send(sender, f"I have no memory entries related to '{topic}'.")

    # "what was decided about <topic>"
    elif text.lower().startswith("what was decided about "):
        topic = text[len("what was decided about "):].strip()
        entries = get_memory()
        matches = search_memory_for_topic(entries, topic, mem_type="decision")
        if matches:
            lines = [f"Decisions related to '{topic}':"]
            lines.extend(format_entry(e) for e in matches)
            send(sender, "\n".join(lines))
        else:
            send(sender, f"No decisions found related to '{topic}'.")

    # "what are the contracts"
    elif text.lower() in ("what are the contracts", "what are the contracts?"):
        entries = get_memory()
        forget_log = load_forget_log()
        forgotten_keys = {item.get("key") for item in forget_log.get("forgotten", [])}
        contracts = [e for e in entries if e.get("type") == "contract" and e.get("key") not in forgotten_keys]
        if contracts:
            lines = [f"Active contracts ({len(contracts)}):"]
            lines.extend(format_entry(e) for e in contracts)
            send(sender, "\n".join(lines))
        else:
            send(sender, "No contract-type memories found.")

    # "forget <key>"
    elif text.lower().startswith("forget "):
        key = text[len("forget "):].strip()
        log = load_forget_log()
        import datetime
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log["forgotten"].append({
            "key": key,
            "forgotten_at": now_str,
            "requested_by": sender,
        })
        save_forget_log(log)
        print(f"[{AGENT_ID}] key '{key}' added to forget log")
        send(sender, f"'{key}' has been forgotten locally. Note: broker has no delete endpoint; entry is excluded from future queries only.")


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
