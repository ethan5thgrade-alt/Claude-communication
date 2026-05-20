#!/usr/bin/env python3
"""
Agent 011 — Message Router
Role: Smart message routing — routes messages based on content, not just recipient ID.
Listens for: route:<intent> prefixed messages, routing_stats
Emits: forwarded messages to best-matching agent
"""
import os
import sys
import json
import time
import requests
import threading
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_011_message_router"
AGENT_NAME = "Agent 011 — Message Router"
ROOM = os.environ.get("MESH_ROOM", "system")

_lock = threading.Lock()
_seen_msg_ids: set = set()
_delivery_stats: dict = {
    "routed": 0,
    "undelivered": 0,
    "by_type": defaultdict(int),
}

# Keyword -> agent_id routing table
KEYWORD_ROUTES = {
    "backup": "agent_005_backup_agent",
    "restore": "agent_005_backup_agent",
    "log": "agent_006_log_aggregator",
    "logs": "agent_006_log_aggregator",
    "metrics": "agent_007_metrics_collector",
    "health": "agent_003_connection_health_monitor",
    "ping": "agent_003_connection_health_monitor",
    "instances": "agent_002_instance_registry",
    "who_is_online": "agent_002_instance_registry",
    "broker": "agent_001_broker_manager",
    "config": "agent_009_configuration_manager",
    "schedule": "agent_010_system_clock",
    "heartbeat": "agent_010_system_clock",
    "event": "agent_008_event_bus_manager",
    "subscribe": "agent_008_event_bus_manager",
    "archive": "agent_016_message_archive",
    "encrypt": "agent_020_message_encryptor",
    "decrypt": "agent_020_message_encryptor",
    "transform": "agent_018_message_transformer",
    "priority": "agent_015_message_priority_queue",
    "rate": "agent_019_message_rate_limiter",
    "duplicate": "agent_014_message_deduplicator",
    "dedup": "agent_014_message_deduplicator",
    "validate": "agent_013_message_validator",
    "broadcast": "agent_012_broadcast_manager",
    "dead_letter": "agent_017_dead_letter_handler",
    "state": "agent_004_state_persistence_manager",
}


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _get_online_instances() -> dict:
    try:
        result = get("/api/instances")
        instances = result.get("instances", [])
        return {inst["id"]: inst for inst in instances if "id" in inst}
    except Exception:
        return {}


def _find_best_agent(intent: str, online: dict) -> str | None:
    """Find best matching agent for an intent string."""
    intent_lower = intent.lower()

    # Check keyword routes first
    for keyword, agent_id in KEYWORD_ROUTES.items():
        if keyword in intent_lower:
            if agent_id in online:
                return agent_id

    # Fuzzy match on instance names
    for iid, info in online.items():
        name = info.get("name", "").lower()
        if any(word in name for word in intent_lower.split()):
            return iid

    return None


def handle_message(msg):
    if msg.get("type") != "message":
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")
    to = msg.get("to", "")

    # Handle routing_stats query
    if to in (AGENT_ID, "all") and text == "routing_stats":
        with _lock:
            stats = dict(_delivery_stats)
            stats["by_type"] = dict(stats["by_type"])
        reply = json.dumps(stats)
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass
        return

    # Handle "route:" prefixed messages
    if text.startswith("route:"):
        intent = text[len("route:"):].strip()
        online = _get_online_instances()
        target = _find_best_agent(intent, online)
        if target:
            try:
                post("/api/send", {"to": target, "text": intent, "from": sender})
                with _lock:
                    _delivery_stats["routed"] += 1
                    _delivery_stats["by_type"][intent.split()[0]] += 1
                reply = f"routed to {target}"
            except Exception as e:
                reply = f"routing failed: {e}"
                with _lock:
                    _delivery_stats["undelivered"] += 1
        else:
            reply = f"no matching agent found for intent: {intent}"
            with _lock:
                _delivery_stats["undelivered"] += 1
        if to in (AGENT_ID, "all"):
            try:
                post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
            except Exception:
                pass


def run_cycle():
    """Scan recent messages for undelivered 'to=all' with no response."""
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    online = _get_online_instances()

    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)

        # Auto-route messages sent to "all" that contain route keywords
        if msg.get("to") == "all":
            text = msg.get("text", "")
            if text.startswith("route:"):
                intent = text[len("route:"):].strip()
                target = _find_best_agent(intent, online)
                if target:
                    try:
                        post("/api/send", {"to": target, "text": intent, "from": msg.get("from", "router")})
                        with _lock:
                            _delivery_stats["routed"] += 1
                    except Exception:
                        pass

    # Prune seen IDs
    if len(_seen_msg_ids) > 10000:
        to_remove = list(_seen_msg_ids)[:5000]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)

    print(f"[{AGENT_ID}] cycle complete — routed: {_delivery_stats['routed']}, undelivered: {_delivery_stats['undelivered']}")


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
