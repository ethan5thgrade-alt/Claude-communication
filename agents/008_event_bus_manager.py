#!/usr/bin/env python3
"""
Agent 008 — Event Bus Manager
Role: Manages system-wide event routing and subscriptions.
Listens for: subscribe <event_type>, emit_event <type> <data>, event_stats
Emits: routed events to registered subscribers
"""
import os
import sys
import json
import time
import requests
import threading
from collections import defaultdict, deque
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_008_event_bus_manager"
AGENT_NAME = "Agent 008 — Event Bus Manager"
ROOM = os.environ.get("MESH_ROOM", "system")

# subscriptions: event_type -> set of instance_ids
_subscriptions: dict = defaultdict(set)
# event counts: event_type -> deque of timestamps (last hour)
_event_log: dict = defaultdict(lambda: deque(maxlen=10000))
_lock = threading.Lock()

# Track processed message IDs to avoid duplicate routing
_seen_msg_ids: set = set()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _route_event(event_type: str, data: dict, from_id: str):
    """Route an event to all subscribers of that type."""
    with _lock:
        subs = set(_subscriptions.get(event_type, set()))
        _event_log[event_type].append(time.time())

    payload_text = json.dumps({
        "event_type": event_type,
        "data": data,
        "from": from_id,
        "ts": datetime.utcnow().isoformat(),
    })

    for sub_id in subs:
        if sub_id == from_id:
            continue
        try:
            post("/api/send", {"to": sub_id, "text": payload_text, "from": AGENT_ID})
        except Exception as e:
            print(f"[{AGENT_ID}] error routing to {sub_id}: {e}")


def handle_message(msg):
    if msg.get("type") != "message":
        # Handle broadcast events with "event:" prefix
        if msg.get("type") == "broadcast":
            text = msg.get("text", "")
            if text.startswith("event:"):
                _handle_event_broadcast(msg)
        return

    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        # Check for event: prefix in routed messages
        text = msg.get("text", "")
        if text.startswith("event:"):
            _handle_event_broadcast(msg)
        return

    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("subscribe "):
        event_type = text[len("subscribe "):].strip()
        with _lock:
            _subscriptions[event_type].add(sender)
        reply = f"subscribed {sender} to event type: {event_type}"
        print(f"[{AGENT_ID}] {reply}")
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("emit_event "):
        rest = text[len("emit_event "):].strip()
        parts = rest.split(" ", 1)
        if len(parts) >= 1:
            event_type = parts[0]
            try:
                data = json.loads(parts[1]) if len(parts) > 1 else {}
            except Exception:
                data = {"raw": parts[1] if len(parts) > 1 else ""}
            _route_event(event_type, data, sender)
            reply = f"event '{event_type}' emitted to {len(_subscriptions.get(event_type, set()))} subscribers"
        else:
            reply = "usage: emit_event <type> <json_data>"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "event_stats":
        cutoff = time.time() - 3600
        with _lock:
            stats = {}
            for etype, timestamps in _event_log.items():
                recent = [t for t in timestamps if t > cutoff]
                stats[etype] = {
                    "last_hour": len(recent),
                    "subscribers": len(_subscriptions.get(etype, set())),
                }
        reply = json.dumps({"event_stats": stats, "total_event_types": len(stats)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def _handle_event_broadcast(msg):
    """Handle messages with 'event:' prefix."""
    text = msg.get("text", "")
    sender = msg.get("from", "unknown")
    if not text.startswith("event:"):
        return
    rest = text[len("event:"):].strip()
    parts = rest.split(" ", 1)
    event_type = parts[0]
    try:
        data = json.loads(parts[1]) if len(parts) > 1 else {}
    except Exception:
        data = {"raw": parts[1] if len(parts) > 1 else ""}
    _route_event(event_type, data, sender)


def run_cycle():
    """Scan recent messages for 'event:' prefixed broadcasts."""
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    now = time.time()
    new_events = 0
    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)

        text = msg.get("text", "")
        if text.startswith("event:"):
            _handle_event_broadcast(msg)
            new_events += 1

    # Prune seen IDs to avoid unbounded growth
    if len(_seen_msg_ids) > 5000:
        to_remove = list(_seen_msg_ids)[:2500]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)

    if new_events:
        print(f"[{AGENT_ID}] routed {new_events} event messages")


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
        time.sleep(10)


if __name__ == "__main__":
    main()
