#!/usr/bin/env python3
"""Agent 021 — Task Orchestrator
Role: Master coordinator for the task lifecycle across all agents.
Listens for: task_overview, clear_stale_tasks <age_minutes>, task_report
Emits: stale task alerts, task stat broadcasts
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_021_task_orchestrator"
AGENT_NAME = "Agent 021 — Task Orchestrator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Track task completions for throughput calculation
_completed_timestamps = []
_cycle_start = time.time()


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


def run_cycle():
    global _completed_timestamps
    tasks = get_tasks()
    now = time.time()

    # Count tasks by status
    counts = {}
    for t in tasks:
        s = t.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    # Find stale pending tasks (>5min)
    stale = []
    for t in tasks:
        if t.get("status") == "pending":
            created = t.get("created_at", "")
            try:
                import datetime
                ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                age = (datetime.datetime.now(datetime.timezone.utc) - ct).total_seconds()
                if age > 300:
                    stale.append(t)
            except Exception:
                pass

    if stale:
        ids = [t.get("id", "?") for t in stale]
        broadcast(f"[task_orchestrator] STALE TASKS (pending >5min): {ids}")

    # Track completed tasks for throughput
    completed_now = [t for t in tasks if t.get("status") == "done"]
    _completed_timestamps = [ts for ts in _completed_timestamps if now - ts < 3600]

    print(f"[{AGENT_ID}] task counts: {counts} | stale: {len(stale)}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "task_overview":
        tasks = get_tasks()
        counts = {}
        oldest_pending = None
        oldest_age = 0
        now = time.time()
        import datetime
        for t in tasks:
            s = t.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
            if s == "pending":
                created = t.get("created_at", "")
                try:
                    ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age = (datetime.datetime.now(datetime.timezone.utc) - ct).total_seconds()
                    if age > oldest_age:
                        oldest_age = age
                        oldest_pending = t.get("id")
                except Exception:
                    pass
        reply = json.dumps({
            "counts": counts,
            "total": len(tasks),
            "oldest_pending_id": oldest_pending,
            "oldest_pending_age_min": round(oldest_age / 60, 1),
        })
        send(sender, reply)

    elif text.startswith("clear_stale_tasks "):
        try:
            age_min = int(text.split(" ", 1)[1])
        except ValueError:
            send(sender, "usage: clear_stale_tasks <age_minutes>")
            return
        tasks = get_tasks()
        import datetime
        cleared = 0
        for t in tasks:
            if t.get("status") in ("pending", "running"):
                created = t.get("created_at", "")
                try:
                    ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age_s = (datetime.datetime.now(datetime.timezone.utc) - ct).total_seconds()
                    if age_s > age_min * 60:
                        api("/api/task", "POST", {
                            "id": t.get("id"),
                            "status": "failed",
                            "result": f"cleared by orchestrator after {age_min}min",
                        })
                        cleared += 1
                except Exception:
                    pass
        send(sender, f"cleared {cleared} stale tasks older than {age_min} minutes")

    elif text == "task_report":
        tasks = get_tasks()
        counts = {}
        durations = []
        assignee_counts = {}
        import datetime
        for t in tasks:
            s = t.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
            assignee = t.get("assignee", "unassigned")
            assignee_counts[assignee] = assignee_counts.get(assignee, 0) + 1
            if s == "done" and t.get("created_at") and t.get("updated_at"):
                try:
                    ct = datetime.datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
                    ut = datetime.datetime.fromisoformat(t["updated_at"].replace("Z", "+00:00"))
                    durations.append((ut - ct).total_seconds())
                except Exception:
                    pass
        total = len(tasks)
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        fail_rate = round(failed / total * 100, 1) if total else 0
        avg_dur = round(sum(durations) / len(durations), 1) if durations else 0
        top_assignees = sorted(assignee_counts.items(), key=lambda x: -x[1])[:3]
        reply = json.dumps({
            "total": total,
            "counts": counts,
            "fail_rate_pct": fail_rate,
            "avg_completion_sec": avg_dur,
            "top_assignees": top_assignees,
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
        time.sleep(30)


if __name__ == "__main__":
    main()
