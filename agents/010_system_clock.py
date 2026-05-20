#!/usr/bin/env python3
"""
Agent 010 — System Clock
Role: Heartbeat and scheduler for recurring agent tasks.
Listens for: schedule <agent_id> <cron_expr> <message>, list_schedules, cancel_schedule <id>
Emits: heartbeat to system room every 60s, fires scheduled tasks
"""
import os
import sys
import json
import time
import uuid
import requests
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_010_system_clock"
AGENT_NAME = "Agent 010 — System Clock"
ROOM = os.environ.get("MESH_ROOM", "system")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULES_PATH = os.path.join(ROOT, "schedules.json")
_lock = threading.Lock()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _load_schedules() -> list:
    if not os.path.exists(SCHEDULES_PATH):
        return []
    try:
        with open(SCHEDULES_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_schedules(schedules: list):
    with open(SCHEDULES_PATH, "w") as f:
        json.dump(schedules, f, indent=2, default=str)


def _parse_cron(cron_expr: str, now: datetime) -> bool:
    """
    Simple cron evaluator supporting: minute hour dom month dow
    Each field can be: * <num> */n
    """
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False
        minute, hour, dom, month, dow = parts

        def matches(field: str, value: int) -> bool:
            if field == "*":
                return True
            if field.startswith("*/"):
                step = int(field[2:])
                return value % step == 0
            return int(field) == value

        return (
            matches(minute, now.minute)
            and matches(hour, now.hour)
            and matches(dom, now.day)
            and matches(month, now.month)
            and matches(dow, now.weekday())
        )
    except Exception:
        return False


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("schedule "):
        # format: schedule <agent_id> <cron_expr> <message>
        # cron_expr is 5 fields separated by spaces, so we parse carefully
        rest = text[len("schedule "):].strip()
        parts = rest.split(" ")
        if len(parts) < 7:  # agent_id + 5 cron fields + message
            reply = "usage: schedule <agent_id> <min> <hour> <dom> <month> <dow> <message>"
        else:
            target_agent = parts[0]
            cron_expr = " ".join(parts[1:6])
            message = " ".join(parts[6:])
            schedule_id = str(uuid.uuid4())[:8]
            entry = {
                "id": schedule_id,
                "agent_id": target_agent,
                "cron_expr": cron_expr,
                "message": message,
                "created_by": sender,
                "created_at": datetime.utcnow().isoformat(),
                "last_fired": None,
            }
            with _lock:
                schedules = _load_schedules()
                schedules.append(entry)
                _save_schedules(schedules)
            reply = json.dumps({"status": "scheduled", "id": schedule_id, "cron": cron_expr, "target": target_agent})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "list_schedules":
        with _lock:
            schedules = _load_schedules()
        reply = json.dumps({"schedules": schedules, "count": len(schedules)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("cancel_schedule "):
        schedule_id = text[len("cancel_schedule "):].strip()
        with _lock:
            schedules = _load_schedules()
            before = len(schedules)
            schedules = [s for s in schedules if s.get("id") != schedule_id]
            after = len(schedules)
            _save_schedules(schedules)
        if before != after:
            reply = f"schedule {schedule_id} cancelled"
        else:
            reply = f"schedule {schedule_id} not found"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    now = datetime.now()
    ts = now.isoformat()

    # Publish heartbeat
    try:
        post("/api/send", {
            "to": "system",
            "text": json.dumps({
                "event": "heartbeat",
                "ts": ts,
                "from": AGENT_ID,
                "utc": datetime.utcnow().isoformat(),
            }),
            "from": AGENT_ID,
        })
        print(f"[{AGENT_ID}] heartbeat at {ts}")
    except Exception as e:
        print(f"[{AGENT_ID}] heartbeat error: {e}")

    # Check scheduled tasks
    with _lock:
        schedules = _load_schedules()
        fired_ids = []
        updated = False

        for entry in schedules:
            cron_expr = entry.get("cron_expr", "")
            if _parse_cron(cron_expr, now):
                last_fired = entry.get("last_fired")
                # Avoid double-firing in the same minute
                if last_fired:
                    try:
                        lf_dt = datetime.fromisoformat(last_fired)
                        if (now - lf_dt).total_seconds() < 55:
                            continue
                    except Exception:
                        pass
                target = entry.get("agent_id", "")
                message = entry.get("message", "")
                try:
                    post("/api/send", {"to": target, "text": message, "from": AGENT_ID})
                    print(f"[{AGENT_ID}] fired schedule {entry['id']}: {message} -> {target}")
                    entry["last_fired"] = now.isoformat()
                    updated = True
                    fired_ids.append(entry["id"])
                except Exception as e:
                    print(f"[{AGENT_ID}] schedule fire error: {e}")

        if updated:
            _save_schedules(schedules)


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    connect.start()
    connect.on_message(handle_message)

    # Initialize schedules file if not present
    if not os.path.exists(SCHEDULES_PATH):
        _save_schedules([])

    print(f"[{AGENT_ID}] online")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
