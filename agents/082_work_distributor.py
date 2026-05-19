#!/usr/bin/env python3
"""Agent 082 — Work Distributor
Role: Intelligently distributes work across Claude instances to maximize parallel throughput.
"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_082_work_distributor"
AGENT_NAME = "Agent 082 — Work Distributor"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

_rr_index = 0  # round-robin pointer


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


def _idle_instances(instances):
    """Return instances with zero in-progress tasks."""
    tasks = _get_tasks()
    busy = set()
    for t in tasks:
        if t.get("status") == "in_progress":
            assignee = t.get("assignee")
            if assignee:
                busy.add(assignee)
    return [i for i in instances if i.get("online") and i.get("id") not in busy]


def run_cycle():
    global _rr_index
    instances = _get_instances()
    if not instances:
        return

    tasks = _get_tasks()
    pending = [t for t in tasks if t.get("status") == "pending" and not t.get("assignee")]
    if not pending:
        return

    idle = _idle_instances(instances)
    if not idle:
        return

    # Assign pending tasks to idle instances via round-robin
    for task in pending:
        target = idle[_rr_index % len(idle)]
        _rr_index += 1
        api("/api/tasks", "POST", {
            "action": "assign",
            "task_id": task.get("id"),
            "assignee": target.get("id"),
        })
        print(f"[{AGENT_ID}] distributed task {task.get('id')} -> {target.get('id')}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("distribute "):
        work_desc = text[len("distribute "):].strip()
        instances = _get_instances()
        online = [i for i in instances if i.get("online") and i.get("id") != AGENT_ID]
        if not online:
            send(sender, "No online instances available.")
            return
        n = len(online)
        created = []
        for idx, inst in enumerate(online):
            chunk_title = f"[{work_desc}] chunk {idx + 1}/{n}"
            result = api("/api/tasks", "POST", {
                "action": "create",
                "title": chunk_title,
                "assignee": inst.get("id"),
                "priority": "normal",
            })
            created.append(f"{inst.get('id')}: {chunk_title}")
        send(sender, f"Distributed '{work_desc}' into {n} chunks:\n" + "\n".join(f"  {c}" for c in created))

    elif text == "workload_balance":
        instances = _get_instances()
        tasks = _get_tasks()
        lines = ["Workload Balance:"]
        for inst in instances:
            inst_id = inst.get("id", "?")
            online = "ONLINE" if inst.get("online") else "offline"
            in_progress = len([t for t in tasks if t.get("assignee") == inst_id
                                and t.get("status") == "in_progress"])
            pending_ct = len([t for t in tasks if t.get("assignee") == inst_id
                               and t.get("status") == "pending"])
            flag = " [OVERLOADED]" if in_progress > 3 else ""
            lines.append(f"  {inst_id} [{online}] in_progress={in_progress} pending={pending_ct}{flag}")
        send(sender, "\n".join(lines))

    elif text == "rebalance":
        instances = _get_instances()
        tasks = _get_tasks()
        online = [i for i in instances if i.get("online")]
        if not online:
            send(sender, "No online instances to rebalance.")
            return

        # Find overloaded instances (>3 in-progress)
        load_map = {}
        for inst in online:
            iid = inst.get("id", "")
            load_map[iid] = [t for t in tasks if t.get("assignee") == iid
                              and t.get("status") in ("pending", "in_progress")]

        avg_load = sum(len(v) for v in load_map.values()) / max(len(load_map), 1)
        moved = 0
        for iid, inst_tasks in list(load_map.items()):
            if len(inst_tasks) > avg_load + 1:
                # Find underloaded instance
                underloaded = sorted(online, key=lambda i: len(load_map.get(i.get("id", ""), [])))[0]
                if underloaded.get("id") == iid:
                    continue
                # Move one pending task
                pending_tasks = [t for t in inst_tasks if t.get("status") == "pending"]
                if pending_tasks:
                    task = pending_tasks[0]
                    api("/api/tasks", "POST", {
                        "action": "assign",
                        "task_id": task.get("id"),
                        "assignee": underloaded.get("id"),
                    })
                    moved += 1
        send(sender, f"Rebalanced: moved {moved} task(s) to less-loaded instances.")


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
        time.sleep(30)


if __name__ == "__main__":
    main()
