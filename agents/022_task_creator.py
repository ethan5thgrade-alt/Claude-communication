#!/usr/bin/env python3
"""Agent 022 — Task Creator
Role: Creates well-formed tasks with validation and routing.
Listens for: create_task <assignee> <title> <priority>, create_task_batch <json_array>, task_template <type>
Emits: task creation confirmations
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_022_task_creator"
AGENT_NAME = "Agent 022 — Task Creator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

TASK_TEMPLATES = {
    "research": {
        "title": "Research: <topic>",
        "priority": "normal",
        "assignee": "",
        "deps": [],
        "notes": "Gather information and summarize findings",
    },
    "build": {
        "title": "Build: <feature>",
        "priority": "normal",
        "assignee": "",
        "deps": [],
        "notes": "Implement the specified feature or component",
    },
    "review": {
        "title": "Review: <artifact>",
        "priority": "normal",
        "assignee": "",
        "deps": [],
        "notes": "Review and provide feedback",
    },
    "test": {
        "title": "Test: <target>",
        "priority": "normal",
        "assignee": "",
        "deps": [],
        "notes": "Verify functionality and report results",
    },
    "deploy": {
        "title": "Deploy: <service>",
        "priority": "high",
        "assignee": "",
        "deps": [],
        "notes": "Deploy service to target environment",
    },
}


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


def get_online_instance_ids():
    result = api("/api/instances")
    instances = result.get("instances", []) if isinstance(result, dict) else []
    return {i.get("id") for i in instances if i.get("online")}


def validate_and_create(assignee, title, priority_str, sender):
    # Validate title
    if not title or not title.strip():
        send(sender, "error: task title cannot be empty")
        return None

    # Validate priority
    try:
        prio = int(priority_str)
        if not 1 <= prio <= 10:
            raise ValueError()
    except (ValueError, TypeError):
        send(sender, f"error: priority must be integer 1-10, got '{priority_str}'")
        return None

    # Validate assignee is online (skip if empty/unassigned)
    if assignee and assignee not in ("", "unassigned"):
        online = get_online_instance_ids()
        if assignee not in online:
            send(sender, f"warning: assignee '{assignee}' is not online; creating task anyway")

    result = api("/api/task", "POST", {
        "title": title.strip(),
        "assignee": assignee if assignee else "",
        "priority": str(prio),
        "deps": [],
    })
    task_id = result.get("id") or result.get("task", {}).get("id", "?")
    return task_id


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("create_task "):
        # create_task <assignee> <title> <priority>
        parts = text.split(" ", 3)
        if len(parts) < 4:
            send(sender, "usage: create_task <assignee> <title> <priority 1-10>")
            return
        _, assignee, title, priority_str = parts
        task_id = validate_and_create(assignee, title, priority_str, sender)
        if task_id:
            send(sender, f"task created: id={task_id} assignee={assignee} title='{title}' priority={priority_str}")

    elif text.startswith("create_task_batch "):
        raw = text[len("create_task_batch "):].strip()
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError("expected JSON array")
        except Exception as e:
            send(sender, f"error: invalid JSON array — {e}")
            return
        created = []
        errors = []
        for item in items:
            assignee = item.get("assignee", "")
            title = item.get("title", "")
            priority = str(item.get("priority", 5))
            task_id = validate_and_create(assignee, title, priority, sender)
            if task_id:
                created.append(task_id)
            else:
                errors.append(title)
        send(sender, f"batch done: created={created} errors={errors}")

    elif text.startswith("task_template "):
        ttype = text.split(" ", 1)[1].strip().lower()
        tmpl = TASK_TEMPLATES.get(ttype)
        if tmpl:
            send(sender, json.dumps(tmpl))
        else:
            send(sender, f"unknown template type '{ttype}'. Available: {list(TASK_TEMPLATES.keys())}")


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
