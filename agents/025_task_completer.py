#!/usr/bin/env python3
"""Agent 025 — Task Completer
Role: Processes task completions, triggers callbacks and next-step chains.
Listens for: task_done <task_id> <result>, task_failed <task_id> <reason>, completion_stats
Emits: completion broadcasts, dependency chain triggers
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_025_task_completer"
AGENT_NAME = "Agent 025 — Task Completer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Local tracking of completions for stats
_completions = []  # list of {"id", "ts", "duration_sec", "success"}


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


def task_duration(task):
    """Compute task duration in seconds from created_at to now."""
    created = task.get("created_at", "")
    if not created:
        return 0
    try:
        ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - ct).total_seconds()
    except Exception:
        return 0


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("task_done "):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            send(sender, "usage: task_done <task_id> <result>")
            return
        task_id, result = parts[1], parts[2]

        # Find the task to get duration info
        tasks = get_tasks()
        task = next((t for t in tasks if t.get("id") == task_id), None)
        duration = task_duration(task) if task else 0

        # Mark complete
        api("/api/task", "POST", {"id": task_id, "status": "done", "result": result})

        # Track completion
        _completions.append({
            "id": task_id,
            "ts": time.time(),
            "duration_sec": duration,
            "success": True,
        })

        # Broadcast completion
        broadcast(f"[task_completer] DONE: task {task_id} completed — {result[:100]}")

        # Check for tasks waiting on this one (dependency chain)
        waiting = [
            t for t in tasks
            if task_id in (t.get("deps") or []) and t.get("status") == "pending"
        ]
        for dep_task in waiting:
            assignee = dep_task.get("assignee", "")
            dep_id = dep_task.get("id", "")
            if assignee:
                send(assignee, f"dependency satisfied: task {dep_id} '{dep_task.get('title','')}' can now start (blocked on {task_id})")
            print(f"[{AGENT_ID}] triggered dependent task {dep_id}")

        send(sender, f"task {task_id} marked done; triggered {len(waiting)} dependent tasks")

    elif text.startswith("task_failed "):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            send(sender, "usage: task_failed <task_id> <reason>")
            return
        task_id, reason = parts[1], parts[2]

        tasks = get_tasks()
        task = next((t for t in tasks if t.get("id") == task_id), None)
        duration = task_duration(task) if task else 0

        api("/api/task", "POST", {"id": task_id, "status": "failed", "result": reason})

        _completions.append({
            "id": task_id,
            "ts": time.time(),
            "duration_sec": duration,
            "success": False,
        })

        # Notify assigner about failure
        send("agent_023_task_assigner", f"task_failed {task_id} reason={reason}")
        broadcast(f"[task_completer] FAILED: task {task_id} — {reason[:100]}")
        send(sender, f"task {task_id} marked failed")

    elif text == "completion_stats":
        now = time.time()
        today_start = now - 86400
        today = [c for c in _completions if c["ts"] >= today_start]
        successes = [c for c in today if c["success"]]
        durations = [c["duration_sec"] for c in successes if c["duration_sec"] > 0]
        avg_dur = round(sum(durations) / len(durations), 1) if durations else 0
        success_rate = round(len(successes) / len(today) * 100, 1) if today else 0
        reply = json.dumps({
            "completed_today": len(today),
            "successes": len(successes),
            "failures": len(today) - len(successes),
            "success_rate_pct": success_rate,
            "avg_duration_sec": avg_dur,
        })
        send(sender, reply)


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
