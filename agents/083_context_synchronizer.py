#!/usr/bin/env python3
"""Agent 083 — Context Synchronizer
Role: Keeps shared context synchronized across all Claude instances.
"""
import os, sys, json, time, requests, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_083_context_synchronizer"
AGENT_NAME = "Agent 083 — Context Synchronizer"
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


def broadcast(text):
    send("all", text)


def _get_context_memories():
    memories = api("/api/memory").get("memory", [])
    return [m for m in memories if m.get("type") == "context"]


def run_cycle():
    """Every 120s: broadcast all context memories to keep all instances aligned."""
    ctx_memories = _get_context_memories()
    if not ctx_memories:
        return
    lines = ["[CONTEXT SYNC BROADCAST]"]
    for m in ctx_memories:
        lines.append(f"  {m.get('key')}: {m.get('value')}")
    broadcast("\n".join(lines))
    print(f"[{AGENT_ID}] broadcast {len(ctx_memories)} context entries")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("share_context "):
        parts = text[len("share_context "):].strip().split(" ", 1)
        if len(parts) < 2:
            send(sender, "Usage: share_context <key> <value>")
            return
        key, value = parts[0], parts[1]
        api("/api/memory", "POST", {"key": key, "value": value, "type": "context"})
        broadcast(f"[CONTEXT] {key}: {value}")
        send(sender, f"Context '{key}' stored and broadcast to all instances.")

    elif text == "context_dump":
        ctx_memories = _get_context_memories()
        if not ctx_memories:
            send(sender, "No context memories found.")
            return
        lines = ["=== Context Briefing Document ==="]
        for m in ctx_memories:
            ts = m.get("ts", "")
            lines.append(f"[{ts}] {m.get('key')}: {m.get('value')}")
        send(sender, "\n".join(lines))

    elif text == "sync_now":
        ctx_memories = _get_context_memories()
        if not ctx_memories:
            send(sender, "No context memories to sync.")
            return
        lines = ["[IMMEDIATE CONTEXT SYNC]"]
        for m in ctx_memories:
            lines.append(f"  {m.get('key')}: {m.get('value')}")
        broadcast("\n".join(lines))
        send(sender, f"Synced {len(ctx_memories)} context entries to all instances.")

    elif text == "stale_context":
        ctx_memories = _get_context_memories()
        now = datetime.datetime.now(datetime.timezone.utc)
        stale = []
        for m in ctx_memories:
            ts_str = m.get("ts", "")
            try:
                ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_hrs = (now - ts).total_seconds() / 3600
                if age_hrs > 1:
                    stale.append((m.get("key"), round(age_hrs, 1)))
            except Exception:
                stale.append((m.get("key"), "unknown age"))
        if not stale:
            send(sender, "All context entries updated within the last hour.")
        else:
            lines = [f"Stale context entries (>1 hr old): {len(stale)}"]
            for key, age in stale:
                lines.append(f"  {key} — {age} hours ago")
            send(sender, "\n".join(lines))


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
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(120)


if __name__ == "__main__":
    main()
