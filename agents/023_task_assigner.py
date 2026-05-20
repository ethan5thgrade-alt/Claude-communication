#!/usr/bin/env python3
"""Agent 023 — Task Assigner
Role: Assigns tasks to best-fit instances based on workload and capability.
Listens for: assign_task <task_id> <instance_id>, workload_report
Emits: assignment notifications
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_023_task_assigner"
AGENT_NAME = "Agent 023 — Task Assigner"
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


def get_tasks():
    result = api("/api/tasks")
    return result.get("tasks", []) if isinstance(result, dict) else []


def get_instances():
    result = api("/api/instances")
    return result.get("instances", []) if isinstance(result, dict) else []


def compute_workload(instance_id, tasks):
    """Count in-progress/running tasks for a given instance."""
    return sum(
        1 for t in tasks
        if t.get("assignee") == instance_id and t.get("status") in ("running", "in_progress")
    )


def run_cycle():
    tasks = get_tasks()
    instances = get_instances()

    # Only consider online instances (exclude self)
    online = [i for i in instances if i.get("online") and i.get("id") != AGENT_ID]
    if not online:
        return

    # Find pending unassigned tasks
    unassigned = [t for t in tasks if t.get("status") == "pending" and not t.get("assignee")]
    if not unassigned:
        return

    for task in unassigned:
        # Find instance with lowest workload
        best = min(online, key=lambda i: compute_workload(i.get("id", ""), tasks))
        best_id = best.get("id", "")
        task_id = task.get("id", "")
        if best_id and task_id:
            api("/api/task", "POST", {
                "id": task_id,
                "assignee": best_id,
                "status": "pending",
            })
            send(best_id, f"task assigned to you: id={task_id} title='{task.get('title', '')}'")
            print(f"[{AGENT_ID}] assigned task {task_id} to {best_id}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("assign_task "):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            send(sender, "usage: assign_task <task_id> <instance_id>")
            return
        _, task_id, instance_id = parts
        result = api("/api/task", "POST", {"id": task_id, "assignee": instance_id})
        send(instance_id, f"task manually assigned: id={task_id}")
        send(sender, f"task {task_id} assigned to {instance_id}: {json.dumps(result)}")

    elif text == "workload_report":
        tasks = get_tasks()
        instances = get_instances()
        report = []
        for inst in instances:
            iid = inst.get("id", "")
            wl = compute_workload(iid, tasks)
            total_assigned = sum(1 for t in tasks if t.get("assignee") == iid)
            report.append({
                "instance": iid,
                "online": inst.get("online", False),
                "in_progress": wl,
                "total_assigned": total_assigned,
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
