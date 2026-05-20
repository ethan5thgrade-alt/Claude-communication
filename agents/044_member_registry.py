#!/usr/bin/env python3
"""Agent 044 — Member Registry
Role: Tracks who's in each room/team, maintains membership history.
Listens for: member_history <room>, active_members <room>, member_since <instance_id>
Emits: membership change events, history reports
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_044_member_registry"
AGENT_NAME = "Agent 044 — Member Registry"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
MEMBERSHIP_LOG = os.path.join(LOG_DIR, "membership.jsonl")

# Last snapshot: instance_id -> {"room": str, "online": bool}
_last_snapshot = {}


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


def _log_event(event_type, instance_id, room, name=""):
    os.makedirs(LOG_DIR, exist_ok=True)
    entry = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "event": event_type,
        "instance_id": instance_id,
        "room": room,
        "name": name,
    }
    with open(MEMBERSHIP_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def run_cycle():
    global _last_snapshot
    result = api("/api/instances")
    instances = result.get("instances", []) if isinstance(result, dict) else []

    current = {}
    for inst in instances:
        iid = inst.get("id", "")
        if iid:
            current[iid] = {
                "room": inst.get("room", "default"),
                "online": inst.get("online", False),
                "name": inst.get("name", iid),
            }

    # Detect joins (newly online) and departures (went offline)
    for iid, state in current.items():
        prev = _last_snapshot.get(iid)
        if prev is None:
            # New instance appeared
            if state["online"]:
                _log_event("join", iid, state["room"], state["name"])
                print(f"[{AGENT_ID}] JOIN: {iid} in room '{state['room']}'")
        elif not prev["online"] and state["online"]:
            _log_event("join", iid, state["room"], state["name"])
            print(f"[{AGENT_ID}] JOIN: {iid} in room '{state['room']}'")
        elif prev["online"] and not state["online"]:
            _log_event("leave", iid, state["room"], state["name"])
            print(f"[{AGENT_ID}] LEAVE: {iid} from room '{state['room']}'")
        elif prev.get("room") != state["room"] and state["online"]:
            _log_event("room_change", iid, state["room"], state["name"])
            print(f"[{AGENT_ID}] ROOM CHANGE: {iid} -> '{state['room']}'")

    # Detect instances that disappeared entirely
    for iid, prev in _last_snapshot.items():
        if iid not in current and prev["online"]:
            _log_event("leave", iid, prev["room"], prev.get("name", iid))
            print(f"[{AGENT_ID}] LEAVE (disappeared): {iid}")

    _last_snapshot = current
    print(f"[{AGENT_ID}] snapshot: {len(current)} instances")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("member_history "):
        room_name = text.split(" ", 1)[1].strip()
        events = []
        if os.path.exists(MEMBERSHIP_LOG):
            with open(MEMBERSHIP_LOG) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("room") == room_name:
                            events.append(entry)
                    except Exception:
                        pass
        send(sender, json.dumps({"room": room_name, "events": events[-50:], "total": len(events)}))

    elif text.startswith("active_members "):
        room_name = text.split(" ", 1)[1].strip()
        active = [
            {"id": iid, "name": state.get("name", iid)}
            for iid, state in _last_snapshot.items()
            if state.get("room") == room_name and state.get("online")
        ]
        send(sender, json.dumps({"room": room_name, "active_members": active, "count": len(active)}))

    elif text.startswith("member_since "):
        instance_id = text.split(" ", 1)[1].strip()
        # Find first join event in membership log
        first_join = None
        if os.path.exists(MEMBERSHIP_LOG):
            with open(MEMBERSHIP_LOG) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("instance_id") == instance_id and entry.get("event") == "join":
                            if first_join is None or entry["ts"] < first_join["ts"]:
                                first_join = entry
                    except Exception:
                        pass
        if first_join:
            ts = first_join["ts"]
            try:
                joined_dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                age = (now_dt - joined_dt).total_seconds()
                send(sender, json.dumps({
                    "instance_id": instance_id,
                    "first_seen": ts,
                    "age_seconds": int(age),
                    "age_hours": round(age / 3600, 2),
                }))
            except Exception:
                send(sender, f"first seen: {ts}")
        else:
            send(sender, f"no membership history for '{instance_id}'")


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
