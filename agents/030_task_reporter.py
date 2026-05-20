#!/usr/bin/env python3
"""Agent 030 — Task Reporter
Role: Generates task completion reports and productivity summaries.
Listens for: daily_report, instance_report <instance_id>, export_tasks <format>
Emits: hourly task report to system room
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_030_task_reporter"
AGENT_NAME = "Agent 030 — Task Reporter"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 3600  # 1 hour


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


def task_duration_sec(task):
    created = task.get("created_at", "")
    updated = task.get("updated_at", "")
    if not created or not updated:
        return 0
    try:
        ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
        ut = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
        return max(0, (ut - ct).total_seconds())
    except Exception:
        return 0


def compile_report(tasks, label="Hourly"):
    counts = {}
    durations = []
    assignee_counts = {}
    for t in tasks:
        s = t.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
        a = t.get("assignee", "unassigned")
        assignee_counts[a] = assignee_counts.get(a, 0) + 1
        if s == "done":
            d = task_duration_sec(t)
            if d > 0:
                durations.append(d)
    total = len(tasks)
    done = counts.get("done", 0)
    failed = counts.get("failed", 0)
    avg_dur = round(sum(durations) / len(durations), 1) if durations else 0
    top_performers = sorted(assignee_counts.items(), key=lambda x: -x[1])[:3]
    return {
        "report": label,
        "total": total,
        "counts": counts,
        "done": done,
        "failed": failed,
        "fail_rate_pct": round(failed / total * 100, 1) if total else 0,
        "avg_duration_sec": avg_dur,
        "top_performers": top_performers,
    }


def run_cycle():
    tasks = get_tasks()
    report = compile_report(tasks, label="Hourly")
    msg = f"[task_reporter] {report['report']} Report: {json.dumps(report)}"
    send("system", msg)
    print(f"[{AGENT_ID}] hourly report posted: {report['total']} tasks")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "daily_report":
        tasks = get_tasks()
        report = compile_report(tasks, label="Daily")
        send(sender, json.dumps(report))

    elif text.startswith("instance_report "):
        instance_id = text.split(" ", 1)[1].strip()
        tasks = get_tasks()
        inst_tasks = [t for t in tasks if t.get("assignee") == instance_id]
        report = compile_report(inst_tasks, label=f"Instance:{instance_id}")
        report["instance_id"] = instance_id
        report["task_history"] = [
            {"id": t.get("id"), "title": t.get("title", ""), "status": t.get("status", ""), "result": t.get("result", "")}
            for t in inst_tasks
        ]
        send(sender, json.dumps(report))

    elif text.startswith("export_tasks "):
        fmt = text.split(" ", 1)[1].strip().lower()
        tasks = get_tasks()
        if fmt == "json":
            send(sender, json.dumps(tasks, default=str))
        elif fmt == "csv":
            lines = ["id,title,status,assignee,priority,created_at,updated_at,result"]
            for t in tasks:
                def esc(v):
                    return str(v or "").replace(",", ";").replace("\n", " ")
                lines.append(",".join([
                    esc(t.get("id")),
                    esc(t.get("title")),
                    esc(t.get("status")),
                    esc(t.get("assignee")),
                    esc(t.get("priority")),
                    esc(t.get("created_at")),
                    esc(t.get("updated_at")),
                    esc(t.get("result")),
                ]))
            send(sender, "\n".join(lines))
        else:
            send(sender, f"unknown format '{fmt}'. Use: json or csv")


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
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
