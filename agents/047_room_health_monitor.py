#!/usr/bin/env python3
"""Agent 047 — Room Health Monitor
Role: Monitors room health — message rate, member activity, task throughput.
Listens for: room_health <room>, all_rooms_health
Emits: flood/dead/member-drop alerts
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_047_room_health_monitor"
AGENT_NAME = "Agent 047 — Room Health Monitor"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# room_name -> {"last_msg_count": int, "member_count": int, "dead_since": float|None}
_room_state = {}
DEAD_THRESHOLD = 1800  # 30 minutes no activity
FLOOD_THRESHOLD = 50  # msgs per 5 min


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


def _count_recent_messages(messages, minutes=5):
    cutoff = time.time() - minutes * 60
    count = 0
    for m in messages:
        ts = m.get("ts", "")
        try:
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if t.timestamp() > cutoff:
                count += 1
        except Exception:
            pass
    return count


def _health_score(msg_rate, online, pending_tasks):
    """Return green/yellow/red and a score 0-100."""
    score = 100
    if online == 0:
        score -= 50
    if msg_rate == 0 and pending_tasks == 0:
        score -= 20
    if msg_rate > FLOOD_THRESHOLD:
        score -= 30
    if score >= 70:
        return "green", score
    if score >= 40:
        return "yellow", score
    return "red", score


def run_cycle():
    rooms_data = api("/api/rooms")
    rooms = rooms_data.get("rooms", []) if isinstance(rooms_data, dict) else []
    now = time.time()

    for room in rooms:
        rname = room.get("name", "")
        online = room.get("online_instances", 0)

        status_data = api(f"/api/status?room={rname}")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
        tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []
        pending_tasks = sum(1 for t in tasks if t.get("status") == "pending")

        msg_rate_5min = _count_recent_messages(messages, 5)

        prev = _room_state.get(rname, {})
        prev_members = prev.get("member_count", online)

        # Check dead room
        if msg_rate_5min == 0 and pending_tasks == 0:
            if "dead_since" not in _room_state.get(rname, {}):
                _room_state.setdefault(rname, {})["dead_since"] = now
            elif now - _room_state[rname]["dead_since"] > DEAD_THRESHOLD:
                broadcast(f"[room_health] DEAD ROOM: '{rname}' — no messages or tasks for >{DEAD_THRESHOLD//60}min")
                _room_state[rname]["dead_since"] = now  # reset to avoid spam
        else:
            if rname in _room_state:
                _room_state[rname].pop("dead_since", None)

        # Check flood
        if msg_rate_5min > FLOOD_THRESHOLD:
            broadcast(f"[room_health] FLOOD: '{rname}' — {msg_rate_5min} msgs in last 5min")

        # Check member drop (>50%)
        if prev_members > 0 and online < prev_members * 0.5:
            broadcast(f"[room_health] MEMBER DROP: '{rname}' — {prev_members} -> {online} members")

        _room_state.setdefault(rname, {}).update({
            "member_count": online,
            "last_msg_rate": msg_rate_5min,
            "last_pending_tasks": pending_tasks,
            "updated_at": now,
        })

    print(f"[{AGENT_ID}] checked health for {len(rooms)} rooms")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("room_health "):
        rname = text.split(" ", 1)[1].strip()
        status_data = api(f"/api/status?room={rname}")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
        tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []
        pending_tasks = sum(1 for t in tasks if t.get("status") == "pending")

        instances_data = api(f"/api/instances?room={rname}")
        instances = instances_data.get("instances", []) if isinstance(instances_data, dict) else []
        online = sum(1 for i in instances if i.get("online"))

        msg_rate = _count_recent_messages(messages, 5)
        color, score = _health_score(msg_rate, online, pending_tasks)

        send(sender, json.dumps({
            "room": rname,
            "health": color,
            "score": score,
            "online_members": online,
            "msgs_last_5min": msg_rate,
            "pending_tasks": pending_tasks,
            "total_messages": len(messages),
        }))

    elif text == "all_rooms_health":
        rooms_data = api("/api/rooms")
        rooms = rooms_data.get("rooms", []) if isinstance(rooms_data, dict) else []
        summary = []
        for room in rooms:
            rname = room.get("name", "")
            online = room.get("online_instances", 0)
            state = _room_state.get(rname, {})
            msg_rate = state.get("last_msg_rate", 0)
            pending = state.get("last_pending_tasks", 0)
            color, score = _health_score(msg_rate, online, pending)
            summary.append({"room": rname, "health": color, "score": score, "online": online})
        send(sender, json.dumps({"rooms": summary}))


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
