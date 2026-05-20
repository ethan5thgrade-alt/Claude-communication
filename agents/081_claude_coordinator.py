#!/usr/bin/env python3
"""Agent 081 — Claude Coordinator
Role: Master coordinator for multiple Claude Code instances working together on a project.
"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_081_claude_coordinator"
AGENT_NAME = "Agent 081 — Claude Coordinator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# track assigned subtasks: task_id -> {subtask_id, instance, done}
_coordination_sessions = {}


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


def _get_instances():
    return api("/api/instances").get("instances", [])


def _get_tasks():
    return api("/api/tasks").get("tasks", [])


def _workload_score(instance):
    """Return a numeric workload score for an instance (lower = less loaded)."""
    return instance.get("workload", 0)


def run_cycle():
    """Every 60s: check for unassigned tasks and distribute to least-loaded instances."""
    instances = _get_instances()
    if not instances:
        return

    # Group by room
    rooms = {}
    for inst in instances:
        r = inst.get("room", "default")
        rooms.setdefault(r, []).append(inst)

    tasks = _get_tasks()
    unassigned = [t for t in tasks if not t.get("assignee") and t.get("status") != "done"]

    if not unassigned:
        return

    # For each room with >1 instance, distribute unassigned tasks
    for room, room_instances in rooms.items():
        if len(room_instances) < 2:
            continue
        online = [i for i in room_instances if i.get("online")]
        if not online:
            continue
        sorted_instances = sorted(online, key=_workload_score)
        for i, task in enumerate(unassigned):
            target = sorted_instances[i % len(sorted_instances)]
            api("/api/tasks", "POST", {
                "action": "assign",
                "task_id": task.get("id"),
                "assignee": target.get("id"),
            })
            print(f"[{AGENT_ID}] assigned task {task.get('id')} to {target.get('id')} (room={room})")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("coordinate "):
        task_desc = text[len("coordinate "):].strip()
        instances = _get_instances()
        online = [i for i in instances if i.get("online") and i.get("id") != AGENT_ID]
        if not online:
            send(sender, "No online instances available to coordinate.")
            return
        # Split task into one subtask per online instance
        subtasks = []
        for idx, inst in enumerate(online):
            subtask_title = f"[{task_desc}] part {idx + 1}/{len(online)}"
            api("/api/tasks", "POST", {
                "action": "create",
                "title": subtask_title,
                "assignee": inst.get("id"),
                "priority": "high",
            })
            subtasks.append({"instance": inst.get("id"), "title": subtask_title})
        send(sender, f"Coordinating '{task_desc}' across {len(online)} instances: " +
             ", ".join(s["instance"] for s in subtasks))

    elif text == "claude_status":
        instances = _get_instances()
        tasks = _get_tasks()
        lines = ["Claude Instance Status:"]
        for inst in instances:
            inst_id = inst.get("id", "?")
            online = "ONLINE" if inst.get("online") else "offline"
            workload = inst.get("workload", 0)
            inst_tasks = [t for t in tasks if t.get("assignee") == inst_id and t.get("status") != "done"]
            lines.append(f"  {inst_id} [{online}] workload={workload} tasks={len(inst_tasks)}")
        send(sender, "\n".join(lines))

    elif text.startswith("sync_context "):
        topic = text[len("sync_context "):].strip()
        memories = api("/api/memory").get("memory", [])
        relevant = [m for m in memories if topic.lower() in str(m.get("key", "")).lower() or
                    topic.lower() in str(m.get("value", "")).lower()]
        if not relevant:
            broadcast(f"[CONTEXT SYNC] topic='{topic}': no stored context found")
        else:
            ctx_lines = [f"[CONTEXT SYNC] topic='{topic}':"]
            for m in relevant:
                ctx_lines.append(f"  {m.get('key')}: {m.get('value')}")
            broadcast("\n".join(ctx_lines))
        send(sender, f"Context synced for topic '{topic}' to all instances.")


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
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
