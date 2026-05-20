#!/usr/bin/env python3
"""Agent 042 — Room Orchestrator
Role: Manages room lifecycle — creation, activity, archiving.
Listens for: create_room <name>, room_members <room>, room_stats <room>, merge_rooms <r1> <r2> <target>
Emits: room_created events, merge notifications
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_042_room_orchestrator"
AGENT_NAME = "Agent 042 — Room Orchestrator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# room_name -> timestamp last activity seen
_room_last_activity = {}
IDLE_THRESHOLD = 3600  # 1 hour


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


def run_cycle():
    rooms_data = api("/api/rooms")
    rooms = rooms_data.get("rooms", []) if isinstance(rooms_data, dict) else []
    now = time.time()

    for room in rooms:
        rname = room.get("name", "")
        online = room.get("online_instances", 0)

        if online == 0:
            if rname not in _room_last_activity:
                _room_last_activity[rname] = now
            idle_since = now - _room_last_activity.get(rname, now)
            if idle_since > IDLE_THRESHOLD:
                print(f"[{AGENT_ID}] room '{rname}' idle for {idle_since//60:.0f}min — marking idle")
        else:
            # Has members — update activity timestamp
            _room_last_activity[rname] = now

        # Log stats for active rooms
        if online > 0:
            status_data = api(f"/api/status?room={rname}")
            msgs = status_data.get("messages", []) if isinstance(status_data, dict) else []
            tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []
            print(f"[{AGENT_ID}] room '{rname}': {online} online, {len(msgs)} msgs, {len(tasks)} tasks")

    print(f"[{AGENT_ID}] monitored {len(rooms)} rooms")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("create_room "):
        room_name = text.split(" ", 1)[1].strip()
        # Create a team with same name as room to register it
        result = api("/api/teams", "POST", {"name": room_name, "room": room_name})
        broadcast(f"room_created: {room_name}")
        send(sender, json.dumps({
            "room": room_name,
            "join_command": f"claude-talk start <id> <name> --room {room_name}",
            "status": "created",
        }))

    elif text.startswith("room_members "):
        room_name = text.split(" ", 1)[1].strip()
        result = api(f"/api/instances?room={room_name}")
        instances = result.get("instances", []) if isinstance(result, dict) else []
        member_list = [
            {"id": i.get("id", "?"), "name": i.get("name", "?"), "online": i.get("online", False)}
            for i in instances
        ]
        send(sender, json.dumps({"room": room_name, "members": member_list, "count": len(member_list)}))

    elif text.startswith("room_stats "):
        room_name = text.split(" ", 1)[1].strip()
        status_data = api(f"/api/status?room={room_name}")
        msgs = status_data.get("messages", []) if isinstance(status_data, dict) else []
        tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []
        memory = status_data.get("memory", []) if isinstance(status_data, dict) else []
        send(sender, json.dumps({
            "room": room_name,
            "message_count": len(msgs),
            "task_count": len(tasks),
            "memory_entries": len(memory),
        }))

    elif text.startswith("merge_rooms "):
        parts = text.split()
        if len(parts) < 4:
            send(sender, "usage: merge_rooms <room1> <room2> <target>")
            return
        room1, room2, target = parts[1], parts[2], parts[3]
        # Notify all members of room1 and room2 to switch to target
        for source_room in [room1, room2]:
            result = api(f"/api/instances?room={source_room}")
            instances = result.get("instances", []) if isinstance(result, dict) else []
            for inst in instances:
                inst_id = inst.get("id", "")
                if inst_id:
                    api("/api/send", "POST", {
                        "to": inst_id,
                        "from": AGENT_ID,
                        "text": f"room_merge: please switch to room '{target}'. Run: claude-talk room {target}",
                        "room": source_room,
                    })
        send(sender, f"merge notification sent to members of '{room1}' and '{room2}' — directing to '{target}'")


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
        time.sleep(300)


if __name__ == "__main__":
    main()
