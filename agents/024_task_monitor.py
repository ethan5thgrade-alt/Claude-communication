#!/usr/bin/env python3
"""Agent 024 — Task Monitor
Role: Watches running tasks, detects timeouts and stuck tasks.
Listens for: task_status <task_id>, set_timeout <task_id> <minutes>, running_tasks
Emits: timeout reminders, escalations to human_bridge
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_024_task_monitor"
AGENT_NAME = "Agent 024 — Task Monitor"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

DEFAULT_TIMEOUT_MIN = 10
ESCALATE_TIMEOUT_MIN = 30

# Custom timeouts per task_id
_custom_timeouts = {}
# Track which tasks have had reminders sent (task_id -> last_reminder_ts)
_reminder_sent = {}
# Track which tasks have been escalated
_escalated = set()


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


def get_tasks():
    result = api("/api/tasks")
    return result.get("tasks", []) if isinstance(result, dict) else []


def task_age_minutes(task):
    started = task.get("updated_at") or task.get("created_at", "")
    if not started:
        return 0
    try:
        dt = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
        age = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 60
        return age
    except Exception:
        return 0


def run_cycle():
    tasks = get_tasks()
    running = [t for t in tasks if t.get("status") in ("running", "in_progress")]

    now = time.time()
    for task in running:
        task_id = task.get("id", "?")
        assignee = task.get("assignee", "")
        age_min = task_age_minutes(task)
        timeout_min = _custom_timeouts.get(task_id, DEFAULT_TIMEOUT_MIN)

        if age_min > ESCALATE_TIMEOUT_MIN and task_id not in _escalated:
            send("human_bridge", f"ESCALATION: task {task_id} '{task.get('title','')}' has been running {age_min:.0f}min (assigned to {assignee})")
            _escalated.add(task_id)
            print(f"[{AGENT_ID}] escalated task {task_id} ({age_min:.0f}min)")
        elif age_min > timeout_min:
            last_reminder = _reminder_sent.get(task_id, 0)
            if now - last_reminder > 300:  # don't re-remind more than once per 5min
                if assignee:
                    send(assignee, f"reminder: task {task_id} '{task.get('title','')}' has been running {age_min:.0f}min — please update status")
                _reminder_sent[task_id] = now
                print(f"[{AGENT_ID}] sent reminder for task {task_id} ({age_min:.0f}min)")

    print(f"[{AGENT_ID}] monitoring {len(running)} running tasks")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("task_status "):
        task_id = text.split(" ", 1)[1].strip()
        tasks = get_tasks()
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if task:
            age_min = task_age_minutes(task)
            reply = json.dumps({
                "id": task_id,
                "title": task.get("title", ""),
                "status": task.get("status", ""),
                "assignee": task.get("assignee", ""),
                "age_minutes": round(age_min, 1),
                "timeout_minutes": _custom_timeouts.get(task_id, DEFAULT_TIMEOUT_MIN),
                "escalated": task_id in _escalated,
            })
            send(sender, reply)
        else:
            send(sender, f"task {task_id} not found")

    elif text.startswith("set_timeout "):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            send(sender, "usage: set_timeout <task_id> <minutes>")
            return
        task_id, minutes_str = parts[1], parts[2]
        try:
            _custom_timeouts[task_id] = int(minutes_str)
            send(sender, f"timeout for task {task_id} set to {minutes_str} minutes")
        except ValueError:
            send(sender, "error: minutes must be an integer")

    elif text == "running_tasks":
        tasks = get_tasks()
        running = [t for t in tasks if t.get("status") in ("running", "in_progress")]
        report = []
        for t in running:
            report.append({
                "id": t.get("id"),
                "title": t.get("title", ""),
                "assignee": t.get("assignee", ""),
                "age_minutes": round(task_age_minutes(t), 1),
                "timeout_minutes": _custom_timeouts.get(t.get("id", ""), DEFAULT_TIMEOUT_MIN),
            })
        send(sender, json.dumps(report))


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
