#!/usr/bin/env python3
"""Agent 027 — Task Priority Manager
Role: Dynamically reorders task queue based on urgency signals.
Listens for: escalate <task_id>, deprioritize <task_id>, priority_queue
Emits: urgent task broadcasts every 5min
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_027_task_priority_manager"
AGENT_NAME = "Agent 027 — Task Priority Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 300  # 5 minutes
URGENT_PENDING_THRESHOLD = 120  # 2 minutes in seconds

# Tracks when we last alerted about an urgent task
_urgent_alerted = {}  # task_id -> last_alert_ts


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


def get_tasks():
    result = api("/api/tasks")
    return result.get("tasks", []) if isinstance(result, dict) else []


def task_pending_age_sec(task):
    import datetime
    created = task.get("created_at", "")
    if not created:
        return 0
    try:
        ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - ct).total_seconds()
    except Exception:
        return 0


def run_cycle():
    tasks = get_tasks()
    now = time.time()
    urgent = [t for t in tasks if str(t.get("priority", "")) == "1" and t.get("status") == "pending"]

    for task in urgent:
        task_id = task.get("id", "")
        age = task_pending_age_sec(task)
        last_alert = _urgent_alerted.get(task_id, 0)
        if age > URGENT_PENDING_THRESHOLD and now - last_alert > CYCLE_INTERVAL:
            broadcast(f"[priority_manager] URGENT TASK PENDING: id={task_id} title='{task.get('title','')}' age={age:.0f}s — all instances please prioritize")
            _urgent_alerted[task_id] = now
            print(f"[{AGENT_ID}] alerted urgent task {task_id} ({age:.0f}s pending)")

    print(f"[{AGENT_ID}] cycle: {len(tasks)} tasks, {len(urgent)} urgent pending")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("escalate "):
        task_id = text.split(" ", 1)[1].strip()
        tasks = get_tasks()
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if not task:
            send(sender, f"task {task_id} not found")
            return
        api("/api/task", "POST", {"id": task_id, "priority": "1"})
        assignee = task.get("assignee", "")
        if assignee:
            send(assignee, f"URGENT: task {task_id} '{task.get('title','')}' has been escalated to priority 1 — please address immediately")
        broadcast(f"[priority_manager] ESCALATED: task {task_id} '{task.get('title','')}' priority set to 1")
        send(sender, f"task {task_id} escalated to priority 1")

    elif text.startswith("deprioritize "):
        task_id = text.split(" ", 1)[1].strip()
        api("/api/task", "POST", {"id": task_id, "priority": "10"})
        send(sender, f"task {task_id} deprioritized to priority 10")

    elif text == "priority_queue":
        tasks = get_tasks()
        pending = [t for t in tasks if t.get("status") == "pending"]
        # Sort by priority (lower number = higher priority), then by creation time
        def sort_key(t):
            try:
                p = int(t.get("priority", 5))
            except (ValueError, TypeError):
                p = 5
            return (p, t.get("created_at", ""))
        pending.sort(key=sort_key)
        queue = [{"id": t.get("id"), "title": t.get("title", ""), "priority": t.get("priority", "normal"), "assignee": t.get("assignee", "")} for t in pending]
        send(sender, json.dumps(queue))


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
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
