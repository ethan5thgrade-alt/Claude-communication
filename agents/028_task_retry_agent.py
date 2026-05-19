#!/usr/bin/env python3
"""Agent 028 — Task Retry Agent
Role: Automatically retries failed tasks with exponential backoff.
Listens for: retry <task_id>, max_retries <task_id> <n>, retry_stats
Emits: retry notifications
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_028_task_retry_agent"
AGENT_NAME = "Agent 028 — Task Retry Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

DEFAULT_MAX_RETRIES = 3
# Backoff delays in seconds: attempt 1 -> 60s, 2 -> 300s, 3 -> 900s
BACKOFF_DELAYS = [60, 300, 900]

# retry tracking: task_id -> {"count": int, "next_retry_at": float, "success": bool|None}
_retry_state = {}
_max_retries = {}  # task_id -> int (custom max)
# Stats tracking
_auto_retried = 0
_retry_success = 0


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


def do_retry(task_id, task, attempt):
    global _auto_retried
    """Re-queue a task by setting it back to pending."""
    api("/api/task", "POST", {
        "id": task_id,
        "status": "pending",
        "result": f"retry attempt {attempt}",
    })
    assignee = task.get("assignee", "")
    if assignee:
        send(assignee, f"task {task_id} '{task.get('title','')}' re-queued (attempt {attempt})")
    print(f"[{AGENT_ID}] retried task {task_id} attempt {attempt}")
    _auto_retried += 1


def run_cycle():
    global _retry_success
    tasks = get_tasks()
    task_map = {t.get("id"): t for t in tasks}
    now = time.time()

    failed = [t for t in tasks if t.get("status") == "failed"]

    for task in failed:
        task_id = task.get("id", "")
        state = _retry_state.get(task_id)
        max_r = _max_retries.get(task_id, DEFAULT_MAX_RETRIES)

        if state is None:
            # First time seeing this failure
            if max_r > 0:
                delay = BACKOFF_DELAYS[0] if BACKOFF_DELAYS else 60
                _retry_state[task_id] = {"count": 0, "next_retry_at": now + delay}
                state = _retry_state[task_id]
            else:
                continue

        count = state.get("count", 0)
        if count >= max_r:
            continue  # exhausted retries

        if now >= state.get("next_retry_at", now):
            do_retry(task_id, task, count + 1)
            state["count"] = count + 1
            # Set next backoff
            if count + 1 < max_r:
                delay = BACKOFF_DELAYS[min(count + 1, len(BACKOFF_DELAYS) - 1)]
                state["next_retry_at"] = now + delay

    # Check for tasks that were retried and succeeded
    for task_id, state in list(_retry_state.items()):
        task = task_map.get(task_id)
        if task and task.get("status") == "done" and state.get("count", 0) > 0:
            if not state.get("success"):
                state["success"] = True
                _retry_success += 1

    print(f"[{AGENT_ID}] cycle: {len(failed)} failed tasks, {len(_retry_state)} tracked for retry")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("retry "):
        task_id = text.split(" ", 1)[1].strip()
        tasks = get_tasks()
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if not task:
            send(sender, f"task {task_id} not found")
            return
        state = _retry_state.get(task_id, {"count": 0})
        attempt = state.get("count", 0) + 1
        do_retry(task_id, task, attempt)
        _retry_state[task_id] = {"count": attempt, "next_retry_at": time.time() + 3600}
        send(sender, f"task {task_id} manually retried (attempt {attempt})")

    elif text.startswith("max_retries "):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            send(sender, "usage: max_retries <task_id> <n>")
            return
        task_id, n_str = parts[1], parts[2]
        try:
            _max_retries[task_id] = int(n_str)
            send(sender, f"max retries for task {task_id} set to {n_str}")
        except ValueError:
            send(sender, "error: n must be an integer")

    elif text == "retry_stats":
        success_rate = round(_retry_success / _auto_retried * 100, 1) if _auto_retried else 0
        reply = json.dumps({
            "auto_retried": _auto_retried,
            "retry_successes": _retry_success,
            "success_after_retry_pct": success_rate,
            "currently_tracked": len(_retry_state),
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
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
