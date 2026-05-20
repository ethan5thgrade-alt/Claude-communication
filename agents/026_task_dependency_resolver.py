#!/usr/bin/env python3
"""Agent 026 — Task Dependency Resolver
Role: Manages task dependency chains — task B can't start until task A completes.
Listens for: task_depends <task_id> <depends_on_task_id>, dependency_graph, unblock <task_id>
Emits: start signals when dependencies complete
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_026_task_dependency_resolver"
AGENT_NAME = "Agent 026 — Task Dependency Resolver"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Local dependency registry: task_id -> set of task_ids it depends on
_deps = {}  # {task_id: [dep_task_id, ...]}
# Track previously completed tasks to detect new completions
_known_done = set()


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


def run_cycle():
    tasks = get_tasks()
    task_map = {t.get("id"): t for t in tasks}

    # Find newly completed tasks
    done_now = {t.get("id") for t in tasks if t.get("status") == "done"}
    newly_done = done_now - _known_done
    _known_done.update(done_now)

    if not newly_done:
        return

    # For each task with dependencies, check if all deps are satisfied
    for task_id, dep_list in list(_deps.items()):
        task = task_map.get(task_id)
        if not task or task.get("status") not in ("pending", "blocked"):
            continue

        satisfied = all(task_map.get(d, {}).get("status") == "done" for d in dep_list)
        if satisfied:
            assignee = task.get("assignee", "")
            if assignee:
                send(assignee, f"all dependencies satisfied for task {task_id} '{task.get('title','')}' — you may begin")
            # Also check broker-level deps
            broker_deps = task.get("deps") or []
            broker_satisfied = all(task_map.get(d, {}).get("status") == "done" for d in broker_deps)
            if broker_satisfied:
                api("/api/task", "POST", {"id": task_id, "status": "pending"})
            print(f"[{AGENT_ID}] unblocked task {task_id}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("task_depends "):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            send(sender, "usage: task_depends <task_id> <depends_on_task_id>")
            return
        task_id, dep_id = parts[1], parts[2]
        if task_id not in _deps:
            _deps[task_id] = []
        if dep_id not in _deps[task_id]:
            _deps[task_id].append(dep_id)
        send(sender, f"registered: task {task_id} depends on {dep_id}")

    elif text == "dependency_graph":
        send(sender, json.dumps(_deps))

    elif text.startswith("unblock "):
        task_id = text.split(" ", 1)[1].strip()
        removed = _deps.pop(task_id, [])
        # Clear broker-level deps too
        api("/api/task", "POST", {"id": task_id, "deps": [], "status": "pending"})
        send(sender, f"cleared {len(removed)} dependencies for task {task_id}")


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
