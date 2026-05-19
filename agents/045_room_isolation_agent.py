#!/usr/bin/env python3
"""Agent 045 — Room Isolation Agent
Role: Enforces room boundaries — detects cross-room message leaks.
Listens for: isolation_report, enforce_strict <room>, audit_room <room>
Emits: isolation violation alerts
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_045_room_isolation_agent"
AGENT_NAME = "Agent 045 — Room Isolation Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
VIOLATIONS_LOG = os.path.join(LOG_DIR, "room_violations.jsonl")

# Strict mode rooms: set of room names
_strict_rooms = set()
# Total violation count
_violation_count = 0


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


def _log_violation(msg_id, sender, sender_room, msg_room):
    global _violation_count
    import datetime
    os.makedirs(LOG_DIR, exist_ok=True)
    entry = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "msg_id": msg_id,
        "sender": sender,
        "sender_room": sender_room,
        "msg_room": msg_room,
    }
    with open(VIOLATIONS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    _violation_count += 1


def run_cycle():
    # Build a map of instance_id -> registered room
    instances_data = api("/api/instances")
    instances = instances_data.get("instances", []) if isinstance(instances_data, dict) else []
    instance_rooms = {i.get("id", ""): i.get("room", "default") for i in instances}

    # Get all messages across all rooms
    status_data = api("/api/status")
    messages = status_data.get("messages", []) if isinstance(status_data, dict) else []

    violations = 0
    for m in messages:
        sender = m.get("from", "")
        msg_room = m.get("room", "")
        if not sender or not msg_room:
            continue
        sender_room = instance_rooms.get(sender, "")
        if sender_room and sender_room != msg_room:
            # Cross-room message detected
            msg_id = m.get("id", "?")
            _log_violation(msg_id, sender, sender_room, msg_room)
            violations += 1
            if msg_room in _strict_rooms:
                broadcast(f"[room_isolation] VIOLATION: {sender} (room: {sender_room}) posted in strict room '{msg_room}'")

    if violations > 0:
        print(f"[{AGENT_ID}] detected {violations} cross-room message(s)")
    else:
        print(f"[{AGENT_ID}] no violations detected, {len(messages)} messages checked")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "isolation_report":
        # Count violations from log
        total = 0
        if os.path.exists(VIOLATIONS_LOG):
            with open(VIOLATIONS_LOG) as f:
                for line in f:
                    if line.strip():
                        total += 1
        send(sender, json.dumps({
            "total_violations": total,
            "session_violations": _violation_count,
            "strict_rooms": list(_strict_rooms),
        }))

    elif text.startswith("enforce_strict "):
        room_name = text.split(" ", 1)[1].strip()
        _strict_rooms.add(room_name)
        send(sender, f"strict mode enabled for room '{room_name}'")

    elif text.startswith("audit_room "):
        room_name = text.split(" ", 1)[1].strip()
        instances_data = api("/api/instances")
        instances = instances_data.get("instances", []) if isinstance(instances_data, dict) else []
        valid_members = {i.get("id", "") for i in instances if i.get("room") == room_name}

        status_data = api(f"/api/status?room={room_name}")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []

        invalid = []
        for m in messages:
            msg_sender = m.get("from", "")
            if msg_sender and msg_sender not in valid_members and msg_sender != "system":
                invalid.append({"from": msg_sender, "id": m.get("id", "?"), "ts": m.get("ts", "")})

        send(sender, json.dumps({
            "room": room_name,
            "total_messages": len(messages),
            "valid_members": list(valid_members),
            "invalid_messages": invalid,
            "clean": len(invalid) == 0,
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
        time.sleep(30)


if __name__ == "__main__":
    main()
