#!/usr/bin/env python3
"""
Agent 015 — Message Priority Queue
Role: Prioritizes messages — URGENT messages jump the queue.
Listens for: URGENT:, CRITICAL:, HIGH: prefixed messages; priority_stats
Emits: forwarded priority messages immediately to target
"""
import os
import sys
import json
import time
import requests
import threading
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_015_message_priority_queue"
AGENT_NAME = "Agent 015 — Message Priority Queue"
ROOM = os.environ.get("MESH_ROOM", "system")

PRIORITY_PREFIXES = {
    "CRITICAL:": 1,
    "URGENT:": 2,
    "HIGH:": 3,
}

_lock = threading.Lock()
_seen_msg_ids: set = set()
# priority_level -> count
_priority_counts: dict = defaultdict(int)
_normal_count = 0
# Queue: list of (priority_int, ts, to, from, text)
_priority_queue: list = []


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _get_priority(text: str) -> tuple:
    """Returns (priority_int, stripped_text). Lower int = higher priority."""
    for prefix, priority in sorted(PRIORITY_PREFIXES.items(), key=lambda x: x[1]):
        if text.startswith(prefix):
            stripped = text[len(prefix):].strip()
            return priority, stripped
    return 99, text  # normal priority


def _deliver_priority_message(to: str, text: str, from_id: str, priority: int):
    """Immediately deliver a priority message."""
    priority_label = {1: "CRITICAL", 2: "URGENT", 3: "HIGH"}.get(priority, "NORMAL")
    annotated_text = f"[{priority_label}] {text}"
    try:
        post("/api/send", {"to": to, "text": annotated_text, "from": AGENT_ID})
        print(f"[{AGENT_ID}] delivered {priority_label} message to {to}: {text[:60]}")
    except Exception as e:
        print(f"[{AGENT_ID}] delivery error: {e}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    # Handle priority_stats query
    if to in (AGENT_ID, "all") and text == "priority_stats":
        with _lock:
            counts = dict(_priority_counts)
            normal = _normal_count
            queue_len = len(_priority_queue)
        labels = {1: "CRITICAL", 2: "URGENT", 3: "HIGH"}
        reply = json.dumps({
            "priority_counts": {labels.get(k, str(k)): v for k, v in counts.items()},
            "normal_count": normal,
            "queue_length": queue_len,
            "total": sum(counts.values()) + normal,
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass
        return

    # Check if this is a priority message directed anywhere
    priority, stripped = _get_priority(text)
    if priority < 99:
        # High-priority: deliver immediately
        with _lock:
            _priority_counts[priority] += 1
        actual_to = to if to != AGENT_ID else sender
        if actual_to and actual_to not in (AGENT_ID, ""):
            _deliver_priority_message(actual_to, stripped, sender, priority)
        else:
            # Broadcast to system room
            _deliver_priority_message("system", stripped, sender, priority)
    elif to in (AGENT_ID, "all"):
        with _lock:
            _normal_count += 1


def run_cycle():
    """Scan recent messages for priority prefixes not yet processed."""
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    new_priority = 0
    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)

        text = msg.get("text", "").strip()
        sender = msg.get("from", "unknown")
        to = msg.get("to", "")

        priority, stripped = _get_priority(text)
        if priority < 99:
            with _lock:
                _priority_counts[priority] += 1
            # Redeliver to target immediately
            if to and to not in (AGENT_ID, "all", ""):
                _deliver_priority_message(to, stripped, sender, priority)
                new_priority += 1
        else:
            with _lock:
                _normal_count += 1

    # Prune seen IDs
    if len(_seen_msg_ids) > 10000:
        to_remove = list(_seen_msg_ids)[:5000]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)

    if new_priority:
        print(f"[{AGENT_ID}] processed {new_priority} priority messages this cycle")


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    connect.start()
    connect.on_message(handle_message)

    print(f"[{AGENT_ID}] online")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(5)


if __name__ == "__main__":
    main()
