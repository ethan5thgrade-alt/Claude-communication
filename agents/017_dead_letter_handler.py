#!/usr/bin/env python3
"""
Agent 017 — Dead Letter Handler
Role: Handles messages sent to offline/unknown instances.
Listens for: dead_letter_queue, flush_dead_letters <instance_id>
Emits: queued messages when target comes online
"""
import os
import sys
import json
import time
import requests
import threading
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_017_dead_letter_handler"
AGENT_NAME = "Agent 017 — Dead Letter Handler"
ROOM = os.environ.get("MESH_ROOM", "system")

_lock = threading.Lock()
_seen_msg_ids: set = set()
# dead_letters: instance_id -> list of message dicts
_dead_letters: dict = defaultdict(list)
# Track online instance IDs
_online_instances: set = set()
MAX_QUEUE_PER_INSTANCE = 100


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _get_online_instance_ids() -> set:
    try:
        result = get("/api/instances")
        return {inst["id"] for inst in result.get("instances", []) if "id" in inst}
    except Exception:
        return set()


def _queue_dead_letter(to: str, msg: dict):
    """Add a message to the dead letter queue for an offline instance."""
    with _lock:
        queue = _dead_letters[to]
        if len(queue) >= MAX_QUEUE_PER_INSTANCE:
            queue.pop(0)  # Evict oldest
        queue.append({
            "msg": msg,
            "queued_at": datetime.utcnow().isoformat(),
        })
    print(f"[{AGENT_ID}] queued dead letter for {to}: {msg.get('text', '')[:60]}")


def _flush_dead_letters(instance_id: str) -> int:
    """Redeliver all queued messages for an instance. Returns count delivered."""
    with _lock:
        queue = list(_dead_letters.get(instance_id, []))
        if instance_id in _dead_letters:
            del _dead_letters[instance_id]

    delivered = 0
    for item in queue:
        msg = item.get("msg", {})
        try:
            post("/api/send", {
                "to": instance_id,
                "text": msg.get("text", ""),
                "from": msg.get("from", AGENT_ID),
            })
            delivered += 1
            time.sleep(0.1)  # Small delay between redeliveries
        except Exception as e:
            print(f"[{AGENT_ID}] redeliver error: {e}")
            # Re-queue on failure
            with _lock:
                _dead_letters[instance_id].append(item)
    return delivered


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "dead_letter_queue":
        with _lock:
            queue_info = {
                iid: {
                    "count": len(msgs),
                    "oldest": msgs[0].get("queued_at") if msgs else None,
                    "newest": msgs[-1].get("queued_at") if msgs else None,
                }
                for iid, msgs in _dead_letters.items()
                if msgs
            }
        reply = json.dumps({
            "dead_letter_queues": queue_info,
            "total_queued": sum(len(v) for v in _dead_letters.values()),
            "total_destinations": len(queue_info),
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("flush_dead_letters "):
        target_id = text[len("flush_dead_letters "):].strip()
        count = _flush_dead_letters(target_id)
        reply = f"flushed {count} dead letters for {target_id}"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _online_instances
    current_online = _get_online_instance_ids()

    # Check for instances that just came online — redeliver their queued messages
    with _lock:
        queued_ids = set(_dead_letters.keys())

    newly_online = current_online & queued_ids - _online_instances
    for iid in newly_online:
        print(f"[{AGENT_ID}] {iid} came online — redelivering queued messages")
        count = _flush_dead_letters(iid)
        if count:
            try:
                post("/api/send", {
                    "to": "system",
                    "text": json.dumps({
                        "event": "dead_letters_flushed",
                        "instance_id": iid,
                        "count": count,
                    }),
                    "from": AGENT_ID,
                })
            except Exception:
                pass

    _online_instances = current_online

    # Scan recent messages for messages to offline instances
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    dead_count = 0
    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)

        to = msg.get("to", "")
        if not to or to in ("all", "system", "you", ""):
            continue
        if to in current_online or to == AGENT_ID:
            continue

        # This message went to an instance that's not currently online
        _queue_dead_letter(to, msg)
        dead_count += 1

    # Prune seen IDs
    if len(_seen_msg_ids) > 10000:
        to_remove = list(_seen_msg_ids)[:5000]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)

    with _lock:
        total_queued = sum(len(v) for v in _dead_letters.values())
    print(f"[{AGENT_ID}] {dead_count} new dead letters, {total_queued} total queued")


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
        time.sleep(60)


if __name__ == "__main__":
    main()
