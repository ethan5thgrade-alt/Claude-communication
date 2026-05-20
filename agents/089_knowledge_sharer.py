#!/usr/bin/env python3
"""Agent 089 — Knowledge Sharer
Role: Extracts learnings from completed tasks and shares with all instances.
"""
import os, sys, json, time, requests, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_089_knowledge_sharer"
AGENT_NAME = "Agent 089 — Knowledge Sharer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

_processed_task_ids = set()


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


def _extract_insight(task):
    """Generate a simple insight string from a completed task."""
    title = task.get("title", "")
    result = task.get("result", "")
    done_by = task.get("done_by", "unknown")
    insight = f"Task '{title}' completed by {done_by}"
    if result:
        snippet = result[:200].replace("\n", " ")
        insight += f": {snippet}"
    return insight


def run_cycle():
    """Every 300s: process completed tasks from last hour and broadcast learnings."""
    tasks = api("/api/tasks").get("tasks", [])
    now = datetime.datetime.now(datetime.timezone.utc)
    one_hour_ago = now - datetime.timedelta(hours=1)

    new_learnings = []
    for task in tasks:
        if task.get("status") != "done":
            continue
        task_id = task.get("id")
        if task_id in _processed_task_ids:
            continue
        # Check if completed recently
        done_ts_str = task.get("done_ts") or task.get("updated_ts") or ""
        try:
            done_ts = datetime.datetime.fromisoformat(done_ts_str.replace("Z", "+00:00"))
            if done_ts < one_hour_ago:
                _processed_task_ids.add(task_id)
                continue
        except Exception:
            pass  # If no timestamp, process it anyway

        _processed_task_ids.add(task_id)
        insight = _extract_insight(task)
        key = f"learned_{task_id}"
        api("/api/memory", "POST", {"key": key, "value": insight, "type": "learned"})
        new_learnings.append(insight)

    if new_learnings:
        summary = f"[KNOWLEDGE SHARE] {len(new_learnings)} new learning(s):\n"
        summary += "\n".join(f"  - {l[:150]}" for l in new_learnings)
        broadcast(summary)
        print(f"[{AGENT_ID}] shared {len(new_learnings)} learnings")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("extract_learning "):
        task_id = text[len("extract_learning "):].strip()
        tasks = api("/api/tasks").get("tasks", [])
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if not task:
            send(sender, f"Task '{task_id}' not found.")
            return
        insight = _extract_insight(task)
        key = f"learned_{task_id}"
        api("/api/memory", "POST", {"key": key, "value": insight, "type": "learned"})
        broadcast(f"[LEARNING] {insight}")
        send(sender, f"Learning extracted and stored: {insight[:200]}")

    elif text == "knowledge_base":
        memories = api("/api/memory").get("memory", [])
        learned = [m for m in memories if m.get("type") == "learned"]
        if not learned:
            send(sender, "Knowledge base is empty.")
            return
        lines = [f"=== Knowledge Base ({len(learned)} entries) ==="]
        for m in learned:
            ts = m.get("ts", "")[:10]
            lines.append(f"[{ts}] {m.get('value', '')[:200]}")
        send(sender, "\n".join(lines))

    elif text.startswith("share_learning "):
        insight = text[len("share_learning "):].strip()
        if not insight:
            send(sender, "Usage: share_learning <insight text>")
            return
        import hashlib
        key = f"learned_manual_{hashlib.sha256(insight.encode()).hexdigest()[:8]}"
        api("/api/memory", "POST", {"key": key, "value": insight, "type": "learned"})
        broadcast(f"[LEARNING] {insight}")
        send(sender, "Learning stored and broadcast.")


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
        time.sleep(300)


if __name__ == "__main__":
    main()
