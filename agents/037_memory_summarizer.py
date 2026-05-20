#!/usr/bin/env python3
"""Agent 037 — Memory Summarizer
Role: Summarizes long memory values into digestible form.
Listens for: summarize_memory <key>, summarize_all_long, memory_digest
Emits: summaries written back to memory
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_037_memory_summarizer"
AGENT_NAME = "Agent 037 — Memory Summarizer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

LONG_VALUE_THRESHOLD = 500  # chars


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


def simple_summarize(text, max_len=200):
    """Heuristic summarization: take first N chars + last sentence fragment."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    # Try to cut at sentence boundary
    cutoff = text[:max_len]
    # Find last period, question mark, or exclamation
    for punct in (".", "?", "!"):
        idx = cutoff.rfind(punct)
        if idx > max_len // 2:
            return cutoff[:idx + 1] + " [summarized]"
    # Fall back to word boundary
    idx = cutoff.rfind(" ")
    if idx > 0:
        return cutoff[:idx] + "... [summarized]"
    return cutoff + "... [summarized]"


def write_summary(key, summary_text):
    api("/api/memory", "POST", {
        "key": key + "_summary",
        "value": summary_text,
        "mem_type": "context",
    })


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("summarize_memory "):
        key = text.split(" ", 1)[1].strip()
        entries = get_memory()
        entry = next((e for e in entries if e.get("key") == key), None)
        if not entry:
            send(sender, f"memory key '{key}' not found")
            return
        value = str(entry.get("value", ""))
        if len(value) <= LONG_VALUE_THRESHOLD:
            send(sender, f"value for '{key}' is only {len(value)} chars — no summary needed")
            return
        summary = simple_summarize(value)
        write_summary(key, summary)
        send(sender, f"summary written as '{key}_summary': {summary}")

    elif text == "summarize_all_long":
        entries = get_memory()
        long_entries = [e for e in entries if len(str(e.get("value", ""))) > LONG_VALUE_THRESHOLD]
        summarized = []
        for entry in long_entries:
            key = entry.get("key", "")
            if key.endswith("_summary"):
                continue
            value = str(entry.get("value", ""))
            summary = simple_summarize(value)
            write_summary(key, summary)
            summarized.append(key)
        send(sender, f"summarized {len(summarized)} long entries: {summarized}")

    elif text == "memory_digest":
        entries = get_memory()
        by_type = {}
        for entry in entries:
            t = entry.get("type", "unknown")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(entry.get("key", ""))

        digest_parts = []
        for t, keys in by_type.items():
            digest_parts.append(f"{t.upper()} ({len(keys)} entries): {', '.join(keys[:5])}{'...' if len(keys) > 5 else ''}")

        digest = "Memory Digest — " + " | ".join(digest_parts)
        send(sender, digest)


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
