#!/usr/bin/env python3
"""Agent 049 — Team Analytics Agent
Role: Tracks team productivity metrics and patterns.
Listens for: team_report <team_id>, top_contributors, collaboration_score <room>
Emits: hourly analytics, productivity reports
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_049_team_analytics_agent"
AGENT_NAME = "Agent 049 — Team Analytics Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
ANALYTICS_LOG = os.path.join(LOG_DIR, "team_analytics.jsonl")


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


def _msgs_per_member(messages):
    counts = {}
    for m in messages:
        sender = m.get("from", "")
        if sender:
            counts[sender] = counts.get(sender, 0) + 1
    return counts


def run_cycle():
    """Compile hourly stats across all rooms."""
    now_dt = datetime.datetime.utcnow()
    one_hour_ago = time.time() - 3600
    os.makedirs(LOG_DIR, exist_ok=True)

    status_data = api("/api/status")
    if not isinstance(status_data, dict):
        return

    messages = status_data.get("messages", [])
    tasks = status_data.get("tasks", [])
    memory = status_data.get("memory", [])
    instances = status_data.get("instances", [])

    # Filter to last hour
    recent_msgs = []
    for m in messages:
        ts = m.get("ts", "")
        try:
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if t.timestamp() > one_hour_ago:
                recent_msgs.append(m)
        except Exception:
            pass

    msg_counts = _msgs_per_member(recent_msgs)
    tasks_created = len([t for t in tasks if t.get("status") != "done"])
    tasks_done = len([t for t in tasks if t.get("status") == "done"])

    approvals_made = sum(
        1 for m in recent_msgs
        if "approve" in m.get("text", "").lower() or "approved" in m.get("text", "").lower()
    )

    entry = {
        "ts": now_dt.isoformat() + "Z",
        "messages_per_member": msg_counts,
        "total_recent_messages": len(recent_msgs),
        "tasks_pending": tasks_created,
        "tasks_done": tasks_done,
        "memory_entries": len(memory),
        "approvals_detected": approvals_made,
        "online_instances": sum(1 for i in instances if i.get("online")),
    }
    with open(ANALYTICS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    print(f"[{AGENT_ID}] hourly analytics logged: {len(recent_msgs)} msgs, {tasks_done} tasks done")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("team_report "):
        team_id = text.split(" ", 1)[1].strip()
        team_info = api(f"/api/teams/{team_id}")
        room = team_info.get("room", team_id) if isinstance(team_info, dict) else team_id
        members = team_info.get("members", []) if isinstance(team_info, dict) else []

        status_data = api(f"/api/status?room={room}")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
        tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []
        memory = status_data.get("memory", []) if isinstance(status_data, dict) else []

        msg_counts = _msgs_per_member(messages)
        report = {
            "team_id": team_id,
            "room": room,
            "members": len(members),
            "total_messages": len(messages),
            "messages_per_sender": msg_counts,
            "tasks_pending": sum(1 for t in tasks if t.get("status") == "pending"),
            "tasks_done": sum(1 for t in tasks if t.get("status") == "done"),
            "memory_entries": len(memory),
        }
        send(sender, json.dumps(report))

    elif text == "top_contributors":
        status_data = api("/api/status")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
        tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []

        msg_counts = _msgs_per_member(messages)
        task_counts = {}
        for t in tasks:
            if t.get("status") == "done":
                done_by = t.get("done_by", t.get("assignee", ""))
                if done_by:
                    task_counts[done_by] = task_counts.get(done_by, 0) + 1

        all_ids = set(msg_counts.keys()) | set(task_counts.keys())
        scores = []
        for iid in all_ids:
            score = msg_counts.get(iid, 0) + task_counts.get(iid, 0)
            scores.append({"instance_id": iid, "messages": msg_counts.get(iid, 0),
                           "tasks_done": task_counts.get(iid, 0), "total_score": score})
        scores.sort(key=lambda x: -x["total_score"])
        send(sender, json.dumps({"top_contributors": scores[:10]}))

    elif text.startswith("collaboration_score "):
        room_name = text.split(" ", 1)[1].strip()
        status_data = api(f"/api/status?room={room_name}")
        messages = status_data.get("messages", []) if isinstance(status_data, dict) else []
        tasks = status_data.get("tasks", []) if isinstance(status_data, dict) else []
        memory = status_data.get("memory", []) if isinstance(status_data, dict) else []

        # Message reciprocity: count unique sender-recipient pairs
        pairs = set()
        senders = set()
        for m in messages:
            s = m.get("from", "")
            t = m.get("to", "")
            if s and t and t != "all":
                pairs.add((s, t))
                senders.add(s)

        reciprocity = len(pairs)
        unique_senders = len(senders)

        # Task sharing: tasks with different creator/assignee
        shared_tasks = sum(
            1 for t in tasks
            if t.get("created_by") and t.get("assignee") and t.get("created_by") != t.get("assignee")
        )

        # Memory contributions
        mem_contributors = len({m.get("by", "") for m in memory if m.get("by")})

        # Score 0-100
        score = 0
        if unique_senders > 1:
            score += min(40, reciprocity * 5)
        score += min(30, shared_tasks * 5)
        score += min(30, mem_contributors * 10)
        score = min(100, score)

        send(sender, json.dumps({
            "room": room_name,
            "collaboration_score": score,
            "unique_senders": unique_senders,
            "message_pairs": reciprocity,
            "shared_tasks": shared_tasks,
            "memory_contributors": mem_contributors,
        }))


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
        time.sleep(3600)


if __name__ == "__main__":
    main()
