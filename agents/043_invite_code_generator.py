#!/usr/bin/env python3
"""Agent 043 — Invite Code Generator
Role: Generates and manages invite codes for teams and rooms.
Listens for: generate_invite [room], validate_invite <code>, share_invite <code> <instance_id>,
             invite_link [room]
Emits: invite codes, join commands, validation results
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_043_invite_code_generator"
AGENT_NAME = "Agent 043 — Invite Code Generator"
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


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("generate_invite"):
        parts = text.split()
        room = parts[1] if len(parts) > 1 else ROOM
        import datetime
        auto_name = f"team_{datetime.datetime.utcnow().strftime('%H%M%S')}"
        result = api("/api/teams", "POST", {"name": auto_name, "room": room})
        if result.get("invite_code"):
            invite = result["invite_code"]
            team_id = result.get("team_id", "")
            join_cmd = f"claude-talk team join {invite} cc2 \"YourName\""
            if TOKEN:
                join_cmd = f"MESH_TOKEN={TOKEN} BROKER_URL={BROKER.replace(':8765','')} claude-talk team join {invite} cc2 \"YourName\""
            send(sender, json.dumps({
                "invite_code": invite,
                "team_id": team_id,
                "room": room,
                "join_command": join_cmd,
                "broker_url": BROKER,
            }))
        else:
            send(sender, f"failed to generate invite: {result}")

    elif text.startswith("validate_invite "):
        code = text.split(" ", 1)[1].strip()
        result = api(f"/api/invite/{code}")
        if result.get("team_id"):
            send(sender, json.dumps({
                "valid": True,
                "invite_code": code,
                "team_id": result.get("team_id"),
                "room": result.get("room"),
                "name": result.get("name"),
            }))
        else:
            send(sender, json.dumps({"valid": False, "invite_code": code, "reason": str(result)}))

    elif text.startswith("share_invite "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: share_invite <code> <instance_id>")
            return
        code, target_id = parts[1], parts[2]
        # Validate invite first
        result = api(f"/api/invite/{code}")
        if result.get("team_id"):
            room = result.get("room", ROOM)
            join_cmd = f"claude-talk team join {code} <your_id> \"<YourName>\""
            if TOKEN:
                join_cmd = f"MESH_TOKEN={TOKEN} BROKER_URL={BROKER} claude-talk team join {code} <your_id> \"<YourName>\""
            api("/api/send", "POST", {
                "to": target_id,
                "from": AGENT_ID,
                "text": f"invite_code: {code} | room: {room} | join: {join_cmd}",
                "room": ROOM,
            })
            send(sender, f"invite code {code} sent to {target_id}")
        else:
            send(sender, f"invalid invite code: {code}")

    elif text.startswith("invite_link"):
        parts = text.split()
        room = parts[1] if len(parts) > 1 else ROOM
        import datetime
        auto_name = f"collab_{datetime.datetime.utcnow().strftime('%H%M%S')}"
        result = api("/api/teams", "POST", {"name": auto_name, "room": room})
        if result.get("invite_code"):
            invite = result["invite_code"]
            # Build the complete one-liner for Angus to paste
            if TOKEN:
                one_liner = (
                    f"MESH_TOKEN={TOKEN} BROKER_URL={BROKER} "
                    f"claude-talk team join {invite} cc2 \"Angus\" --room {room}"
                )
            else:
                one_liner = f"BROKER_URL={BROKER} claude-talk team join {invite} cc2 \"Angus\" --room {room}"
            send(sender, f"invite_link for room '{room}':\n{one_liner}")
        else:
            send(sender, f"failed to create invite link: {result}")


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
            time.sleep(30)
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")


if __name__ == "__main__":
    main()
