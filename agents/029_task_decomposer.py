#!/usr/bin/env python3
"""Agent 029 — Task Decomposer
Role: Breaks large complex tasks into smaller executable subtasks.
Listens for: decompose <title> <description>, decompose_and_assign <title> <desc> <team>, merge_results <parent_task_id>
Emits: subtask creation confirmations
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_029_task_decomposer"
AGENT_NAME = "Agent 029 — Task Decomposer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Map: parent_task_id -> [subtask_ids]
_parent_subtasks = {}


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


def generate_subtasks(title, description):
    """Heuristic decomposition of a task into 3-5 subtasks."""
    title_lower = title.lower()
    desc_lower = description.lower()

    # Detect task type from keywords
    if any(w in title_lower + desc_lower for w in ["deploy", "release", "ship"]):
        return [
            f"Test: verify {title} is ready",
            f"Build: compile/package {title}",
            f"Review: final sign-off on {title}",
            f"Deploy: execute deployment of {title}",
            f"Monitor: post-deploy health check for {title}",
        ]
    elif any(w in title_lower + desc_lower for w in ["research", "investigate", "analyze"]):
        return [
            f"Gather: collect sources for {title}",
            f"Review: read and annotate sources for {title}",
            f"Synthesize: summarize findings for {title}",
            f"Report: write report for {title}",
        ]
    elif any(w in title_lower + desc_lower for w in ["build", "implement", "create", "develop"]):
        return [
            f"Design: plan approach for {title}",
            f"Implement: core logic for {title}",
            f"Test: unit tests for {title}",
            f"Review: code review for {title}",
            f"Document: write docs for {title}",
        ]
    else:
        # Generic decomposition
        return [
            f"Clarify: define scope for '{title}'",
            f"Plan: outline steps for '{title}'",
            f"Execute: main work on '{title}'",
            f"Verify: validate results of '{title}'",
        ]


def create_subtask(title, assignee="", parent_id=None):
    result = api("/api/task", "POST", {
        "title": title,
        "assignee": assignee,
        "priority": "normal",
        "deps": [parent_id] if parent_id else [],
    })
    return result.get("id") or result.get("task", {}).get("id")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("decompose "):
        rest = text[len("decompose "):].strip()
        # Expect: <title> | <description> (pipe-separated or space-split on first space)
        if "|" in rest:
            title, description = rest.split("|", 1)
        else:
            parts = rest.split(" ", 1)
            title = parts[0]
            description = parts[1] if len(parts) > 1 else ""
        title, description = title.strip(), description.strip()

        subtask_titles = generate_subtasks(title, description)
        subtask_ids = []
        for st_title in subtask_titles:
            st_id = create_subtask(st_title)
            if st_id:
                subtask_ids.append(st_id)

        # Create a parent task to track them
        parent_result = api("/api/task", "POST", {
            "title": f"[PARENT] {title}",
            "priority": "normal",
            "deps": subtask_ids,
        })
        parent_id = parent_result.get("id") or parent_result.get("task", {}).get("id")
        if parent_id:
            _parent_subtasks[parent_id] = subtask_ids

        send(sender, json.dumps({
            "parent_task_id": parent_id,
            "subtask_ids": subtask_ids,
            "subtask_titles": subtask_titles,
        }))

    elif text.startswith("decompose_and_assign "):
        rest = text[len("decompose_and_assign "):].strip()
        # Format: <title> | <desc> | <team_instance_id,...>
        parts = rest.split("|")
        if len(parts) < 3:
            send(sender, "usage: decompose_and_assign <title> | <desc> | <team_ids_comma_separated>")
            return
        title = parts[0].strip()
        description = parts[1].strip()
        team_ids = [t.strip() for t in parts[2].split(",") if t.strip()]

        subtask_titles = generate_subtasks(title, description)
        subtask_ids = []
        for i, st_title in enumerate(subtask_titles):
            assignee = team_ids[i % len(team_ids)] if team_ids else ""
            st_id = create_subtask(st_title, assignee=assignee)
            if st_id:
                subtask_ids.append(st_id)
                if assignee:
                    send(assignee, f"subtask assigned: {st_id} '{st_title}'")

        parent_result = api("/api/task", "POST", {
            "title": f"[PARENT] {title}",
            "priority": "normal",
            "deps": subtask_ids,
        })
        parent_id = parent_result.get("id") or parent_result.get("task", {}).get("id")
        if parent_id:
            _parent_subtasks[parent_id] = subtask_ids

        send(sender, json.dumps({
            "parent_task_id": parent_id,
            "subtask_ids": subtask_ids,
            "assigned_to": team_ids,
        }))

    elif text.startswith("merge_results "):
        parent_id = text.split(" ", 1)[1].strip()
        subtask_ids = _parent_subtasks.get(parent_id, [])
        if not subtask_ids:
            send(sender, f"no subtasks tracked for parent task {parent_id}")
            return

        tasks = get_tasks()
        task_map = {t.get("id"): t for t in tasks}

        outputs = []
        all_done = True
        for st_id in subtask_ids:
            st = task_map.get(st_id)
            if st:
                result = st.get("result", "")
                outputs.append(f"[{st_id}] {st.get('title','')}: {result}")
                if st.get("status") != "done":
                    all_done = False
            else:
                outputs.append(f"[{st_id}] (not found)")
                all_done = False

        combined = "\n".join(outputs)
        if all_done:
            api("/api/task", "POST", {"id": parent_id, "status": "done", "result": combined[:500]})
            send(sender, f"parent task {parent_id} marked done. Combined results:\n{combined}")
        else:
            send(sender, f"not all subtasks done yet. Partial results:\n{combined}")


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
