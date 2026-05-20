#!/usr/bin/env python3
"""Agent 048 — Cross-Room Coordinator
Role: Facilitates controlled cross-room communication.
Listens for: bridge <room1> <room2>, cross_post <room> <message>, relay <instance_id> <message>,
             unbridge <room1> <room2>
Emits: bridged messages, relay confirmations
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_048_cross_room_coordinator"
AGENT_NAME = "Agent 048 — Cross-Room Coordinator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

BRIDGE_TTL = 3600  # 1 hour auto-expiry
# bridges: frozenset({room1, room2}) -> {"created_at": float, "rooms": [r1, r2]}
_bridges = {}
# seen message IDs to prevent infinite relay loops
_seen_msg_ids = set()
MAX_SEEN = 10000


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


def _send_to_room(room, text, original_sender=""):
    api("/api/send", "POST", {
        "to": "all",
        "from": AGENT_ID,
        "text": f"[bridge from {original_sender}] {text}",
        "room": room,
    })


def run_cycle():
    """Check active bridges, expire old ones, forward messages."""
    now = time.time()
    expired = []
    for key, bridge in list(_bridges.items()):
        if now - bridge["created_at"] > BRIDGE_TTL:
            expired.append((key, bridge["rooms"]))

    for key, rooms in expired:
        del _bridges[key]
        broadcast(f"[cross_room] bridge between '{rooms[0]}' and '{rooms[1]}' expired (1hr TTL)")

    if _bridges:
        print(f"[{AGENT_ID}] active bridges: {len(_bridges)}")
    else:
        print(f"[{AGENT_ID}] no active bridges")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")
    msg_id = msg.get("id", "")
    msg_room = msg.get("room", "")

    # Bridge forwarding: if this message is from a bridged room, relay it
    if msg_id and msg_id not in _seen_msg_ids and to == "all":
        for key, bridge in _bridges.items():
            rooms = bridge["rooms"]
            if msg_room in rooms and sender != AGENT_ID:
                if len(_seen_msg_ids) > MAX_SEEN:
                    _seen_msg_ids.clear()
                _seen_msg_ids.add(msg_id)
                # Forward to the other room
                other_room = rooms[1] if msg_room == rooms[0] else rooms[0]
                _send_to_room(other_room, text, sender)

    # Only respond to messages addressed to us
    if to not in (AGENT_ID, "all"):
        return

    if text.startswith("bridge "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: bridge <room1> <room2>")
            return
        room1, room2 = parts[1], parts[2]
        key = frozenset({room1, room2})
        if key in _bridges:
            send(sender, f"bridge between '{room1}' and '{room2}' already active")
            return
        _bridges[key] = {"created_at": time.time(), "rooms": [room1, room2]}
        send(sender, f"bridge created between '{room1}' and '{room2}' (expires in 1hr)")

    elif text.startswith("cross_post "):
        rest = text[len("cross_post "):].strip()
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            send(sender, "usage: cross_post <room> <message>")
            return
        target_room, message = parts[0], parts[1]
        api("/api/send", "POST", {
            "to": "all",
            "from": AGENT_ID,
            "text": f"[announcement from {sender}] {message}",
            "room": target_room,
        })
        send(sender, f"cross-posted to room '{target_room}'")

    elif text.startswith("relay "):
        rest = text[len("relay "):].strip()
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            send(sender, "usage: relay <instance_id> <message>")
            return
        target_id, message = parts[0], parts[1]
        # Find which room the target is in
        instances_data = api("/api/instances")
        instances = instances_data.get("instances", []) if isinstance(instances_data, dict) else []
        target_room = ROOM
        for inst in instances:
            if inst.get("id") == target_id:
                target_room = inst.get("room", ROOM)
                break
        api("/api/send", "POST", {
            "to": target_id,
            "from": AGENT_ID,
            "text": f"[relay from {sender}] {message}",
            "room": target_room,
        })
        send(sender, f"relayed message to '{target_id}' in room '{target_room}'")

    elif text.startswith("unbridge "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: unbridge <room1> <room2>")
            return
        room1, room2 = parts[1], parts[2]
        key = frozenset({room1, room2})
        if key in _bridges:
            del _bridges[key]
            send(sender, f"bridge between '{room1}' and '{room2}' removed")
        else:
            send(sender, f"no active bridge between '{room1}' and '{room2}'")


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
