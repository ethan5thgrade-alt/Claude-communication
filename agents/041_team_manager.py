#!/usr/bin/env python3
"""Agent 041 — Team Manager
Role: Creates, monitors, and manages teams in the mesh.
Listens for: create_team <name> [room], team_status <team_id>, list_teams, team_activity <team_id>
Emits: team creation confirmations, team status reports, alerts for empty teams
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_041_team_manager"
AGENT_NAME = "Agent 041 — Team Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Track teams with 0 online members: team_id -> timestamp first seen empty
_empty_team_since = {}
ALERT_THRESHOLD = 600  # 10 minutes


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
    # GET /api/rooms, count teams vs rooms
    rooms_data = api("/api/rooms")
    rooms = rooms_data.get("rooms", []) if isinstance(rooms_data, dict) else []

    # GET /api/status for full state
    status = api("/api/status")
    instances = status.get("instances", []) if isinstance(status, dict) else []

    now = time.time()
    room_online = {}
    for inst in instances:
        r = inst.get("room", "default")
        if inst.get("online"):
            room_online[r] = room_online.get(r, 0) + 1

    for room in rooms:
        rname = room.get("name", "")
        online = room_online.get(rname, 0)
        if online == 0:
            if rname not in _empty_team_since:
                _empty_team_since[rname] = now
            elif now - _empty_team_since[rname] > ALERT_THRESHOLD:
                broadcast(f"[team_manager] ALERT: room '{rname}' has had 0 online members for >{ALERT_THRESHOLD//60}min")
                _empty_team_since.pop(rname, None)
        else:
            _empty_team_since.pop(rname, None)

    print(f"[{AGENT_ID}] monitored {len(rooms)} rooms, {len(instances)} instances")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("create_team "):
        parts = text.split()
        if len(parts) < 2:
            send(sender, "usage: create_team <name> [room]")
            return
        name = parts[1]
        room = parts[2] if len(parts) > 2 else name
        result = api("/api/teams", "POST", {"name": name, "room": room})
        if result.get("team_id"):
            invite = result.get("invite_code", "")
            tid = result.get("team_id", "")
            send(sender, json.dumps({
                "team_id": tid,
                "invite_code": invite,
                "room": room,
                "join_command": f"claude-talk team join {invite} cc2 \"YourName\"",
            }))
        else:
            send(sender, f"failed to create team: {result}")

    elif text.startswith("team_status "):
        team_id = text.split(" ", 1)[1].strip()
        result = api(f"/api/teams/{team_id}")
        if isinstance(result, dict):
            members = result.get("members", [])
            send(sender, json.dumps({
                "team_id": team_id,
                "member_count": len(members),
                "members": members,
            }))
        else:
            send(sender, f"could not get team status for {team_id}")

    elif text == "list_teams":
        rooms_data = api("/api/rooms")
        rooms = rooms_data.get("rooms", []) if isinstance(rooms_data, dict) else []
        status_data = api("/api/status")
        instances = status_data.get("instances", []) if isinstance(status_data, dict) else []
        room_online = {}
        for inst in instances:
            r = inst.get("room", "default")
            if inst.get("online"):
                room_online[r] = room_online.get(r, 0) + 1
        lines = [f"{'ROOM':<20} {'ONLINE':>8}"]
        lines.append("-" * 30)
        for r in rooms:
            rn = r.get("name", "?")
            on = room_online.get(rn, 0)
            lines.append(f"{rn:<20} {on:>8}")
        send(sender, "\n".join(lines))

    elif text.startswith("team_activity "):
        team_id = text.split(" ", 1)[1].strip()
        # Get team info to find room
        team_info = api(f"/api/teams/{team_id}")
        room = team_info.get("room", team_id) if isinstance(team_info, dict) else team_id
        status_data = api(f"/api/status?room={room}")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
        one_hour_ago = time.time() - 3600
        import datetime
        recent = []
        for m in messages:
            ts = m.get("ts", "")
            try:
                t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t.timestamp() > one_hour_ago:
                    recent.append(m)
            except Exception:
                pass
        send(sender, f"team '{team_id}' (room: {room}): {len(recent)} messages in last hour")


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
        time.sleep(60)


if __name__ == "__main__":
    main()
