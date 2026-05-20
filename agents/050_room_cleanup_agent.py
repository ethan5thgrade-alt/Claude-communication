#!/usr/bin/env python3
"""Agent 050 — Room Cleanup Agent
Role: Archives inactive rooms and cleans up stale state.
Listens for: archive_room <room>, cleanup_report, restore_room <room>
Emits: cleanup notifications
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_050_room_cleanup_agent"
AGENT_NAME = "Agent 050 — Room Cleanup Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive", "rooms")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CLEANUP_LOG = os.path.join(LOG_DIR, "cleanup.jsonl")

INACTIVE_THRESHOLD = 86400  # 24 hours
# room_name -> timestamp of last activity detected
_room_last_activity = {}
_cleanup_history = []


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


def _archive_room(room_name):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    now_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Fetch room state
    status_data = api(f"/api/status?room={room_name}")
    messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
    tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []

    archive_path = os.path.join(ARCHIVE_DIR, f"{room_name}_{now_str}.json")
    archive_data = {
        "room": room_name,
        "archived_at": datetime.datetime.utcnow().isoformat() + "Z",
        "messages": messages,
        "tasks": tasks,
    }
    with open(archive_path, "w") as f:
        json.dump(archive_data, f, indent=2)

    entry = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "room": room_name,
        "archive_path": archive_path,
        "message_count": len(messages),
        "task_count": len(tasks),
    }
    with open(CLEANUP_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    _cleanup_history.append(entry)
    return archive_path, len(messages), len(tasks)


def _last_activity(messages):
    """Return timestamp of most recent message, or None."""
    latest = None
    for m in messages:
        ts = m.get("ts", "")
        try:
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if latest is None or t > latest:
                latest = t
        except Exception:
            pass
    return latest


def run_cycle():
    rooms_data = api("/api/rooms")
    rooms = rooms_data.get("rooms", []) if isinstance(rooms_data, dict) else []
    now = time.time()

    for room in rooms:
        rname = room.get("name", "")
        online = room.get("online_instances", 0)
        if online > 0:
            _room_last_activity[rname] = now
            continue

        status_data = api(f"/api/status?room={rname}")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
        last_msg = _last_activity(messages)

        if last_msg:
            last_ts = last_msg.timestamp()
            _room_last_activity[rname] = max(_room_last_activity.get(rname, 0), last_ts)
        elif rname not in _room_last_activity:
            _room_last_activity[rname] = now

        inactive_for = now - _room_last_activity.get(rname, now)
        if inactive_for > INACTIVE_THRESHOLD:
            print(f"[{AGENT_ID}] archiving inactive room '{rname}' ({inactive_for/3600:.1f}h)")
            try:
                archive_path, msg_count, task_count = _archive_room(rname)
                broadcast(f"[room_cleanup] archived room '{rname}': {msg_count} msgs, {task_count} tasks -> {archive_path}")
                _room_last_activity.pop(rname, None)
            except Exception as e:
                print(f"[{AGENT_ID}] archive error for '{rname}': {e}")

    print(f"[{AGENT_ID}] cleanup cycle done, {len(rooms)} rooms checked")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("archive_room "):
        room_name = text.split(" ", 1)[1].strip()
        try:
            archive_path, msg_count, task_count = _archive_room(room_name)
            send(sender, f"archived room '{room_name}': {msg_count} messages, {task_count} tasks -> {archive_path}")
        except Exception as e:
            send(sender, f"failed to archive room '{room_name}': {e}")

    elif text == "cleanup_report":
        cutoff = time.time() - 86400
        recent = [e for e in _cleanup_history if
                  datetime.datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).timestamp() > cutoff]

        # Also check log file
        log_recent = []
        if os.path.exists(CLEANUP_LOG):
            with open(CLEANUP_LOG) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts = entry.get("ts", "")
                        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if t.timestamp() > cutoff:
                            log_recent.append(entry)
                    except Exception:
                        pass

        send(sender, json.dumps({
            "last_24h_cleanups": len(log_recent),
            "recent_archives": log_recent[-10:],
        }))

    elif text.startswith("restore_room "):
        room_name = text.split(" ", 1)[1].strip()
        # Find most recent archive for this room
        if not os.path.exists(ARCHIVE_DIR):
            send(sender, f"no archives found")
            return
        archives = sorted([
            f for f in os.listdir(ARCHIVE_DIR)
            if f.startswith(f"{room_name}_") and f.endswith(".json")
        ])
        if not archives:
            send(sender, f"no archive found for room '{room_name}'")
            return
        latest = archives[-1]
        archive_path = os.path.join(ARCHIVE_DIR, latest)
        try:
            with open(archive_path) as f:
                archive_data = json.load(f)
            messages = archive_data.get("messages", [])
            # Re-inject messages by sending them
            count = 0
            for m in messages[:20]:  # limit to avoid overwhelming broker
                api("/api/send", "POST", {
                    "to": "all",
                    "from": AGENT_ID,
                    "text": f"[restored from archive] {m.get('from','?')}: {m.get('text','')}",
                    "room": room_name,
                })
                count += 1
            send(sender, f"restored room '{room_name}' from {latest}: {count} messages re-injected")
        except Exception as e:
            send(sender, f"restore failed: {e}")


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
        time.sleep(3600)


if __name__ == "__main__":
    main()
