#!/usr/bin/env python3
"""Agent 086 — Progress Tracker
Role: Tracks and reports progress across all Claude instances and tasks.
"""
import os, sys, json, time, requests, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_086_progress_tracker"
AGENT_NAME = "Agent 086 — Progress Tracker"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# milestone_name -> {task_ids: [...], created_ts}
_milestones = {}
# history of completed task counts for velocity calculation
_velocity_history = []  # list of (ts, done_count)


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


def _get_tasks():
    return api("/api/tasks").get("tasks", [])


def _calc_velocity():
    """Calculate tasks/hr based on velocity history."""
    if len(_velocity_history) < 2:
        return 0.0
    oldest_ts, oldest_count = _velocity_history[0]
    newest_ts, newest_count = _velocity_history[-1]
    elapsed_hrs = (newest_ts - oldest_ts).total_seconds() / 3600
    if elapsed_hrs < 0.001:
        return 0.0
    return (newest_count - oldest_count) / elapsed_hrs


def run_cycle():
    tasks = _get_tasks()
    done_count = len([t for t in tasks if t.get("status") == "done"])
    now = datetime.datetime.now(datetime.timezone.utc)
    _velocity_history.append((now, done_count))
    # Keep only last 24 entries (24 minutes of history at 60s cycle)
    if len(_velocity_history) > 24:
        _velocity_history.pop(0)

    # Check milestones
    for mname, mdata in _milestones.items():
        done_ids = {t.get("id") for t in tasks if t.get("status") == "done"}
        if all(tid in done_ids for tid in mdata.get("task_ids", [])):
            if not mdata.get("notified"):
                broadcast(f"[MILESTONE COMPLETE] '{mname}' — all tasks done!")
                mdata["notified"] = True


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "progress":
        tasks = _get_tasks()
        total = len(tasks)
        done = len([t for t in tasks if t.get("status") == "done"])
        in_prog = len([t for t in tasks if t.get("status") == "in_progress"])
        pending = len([t for t in tasks if t.get("status") == "pending"])
        blocked = len([t for t in tasks if t.get("status") == "blocked"])
        pct = round(done / total * 100, 1) if total else 0
        velocity = _calc_velocity()
        lines = [
            f"=== Progress Dashboard ===",
            f"  Total:       {total}",
            f"  Done:        {done} ({pct}%)",
            f"  In Progress: {in_prog}",
            f"  Pending:     {pending}",
            f"  Blocked:     {blocked}",
            f"  Velocity:    {round(velocity, 2)} tasks/hr",
        ]
        send(sender, "\n".join(lines))

    elif text.startswith("eta "):
        goal = text[len("eta "):].strip()
        tasks = _get_tasks()
        pending = len([t for t in tasks if t.get("status") in ("pending", "in_progress")])
        velocity = _calc_velocity()
        if velocity <= 0:
            send(sender, f"ETA for '{goal}': velocity is 0 tasks/hr — cannot estimate.")
        else:
            eta_hrs = pending / velocity
            send(sender, f"ETA for '{goal}': ~{round(eta_hrs, 1)} hrs at {round(velocity, 2)} tasks/hr "
                         f"({pending} tasks remaining).")

    elif text.startswith("milestone "):
        # milestone <name> <task_id1> <task_id2> ...
        parts = text[len("milestone "):].strip().split()
        if len(parts) < 2:
            send(sender, "Usage: milestone <name> <task_id1> [task_id2 ...]")
            return
        mname = parts[0]
        task_ids = parts[1:]
        _milestones[mname] = {"task_ids": task_ids, "notified": False}
        send(sender, f"Milestone '{mname}' set with {len(task_ids)} task(s): {', '.join(task_ids)}")

    elif text == "blocker_report":
        tasks = _get_tasks()
        task_map = {t.get("id"): t for t in tasks}
        blockers = []
        for t in tasks:
            deps = t.get("deps", [])
            unmet = [d for d in deps if task_map.get(d, {}).get("status") != "done"]
            if unmet and t.get("status") != "done":
                blockers.append((t.get("id"), t.get("title", ""), unmet))
        if not blockers:
            send(sender, "No blocked tasks found.")
        else:
            lines = [f"Blocked Tasks ({len(blockers)}):"]
            for tid, title, unmet in blockers:
                lines.append(f"  {tid} '{title}' — waiting on: {', '.join(unmet)}")
            send(sender, "\n".join(lines))


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
