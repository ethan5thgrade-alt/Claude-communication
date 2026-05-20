#!/usr/bin/env python3
"""Agent 087 — Load Balancer
Role: Balances computational load across Claude instances.
"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_087_load_balancer"
AGENT_NAME = "Agent 087 — Load Balancer"
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


def broadcast(text):
    send("all", text)


def _get_instances():
    return api("/api/instances").get("instances", [])


def _get_tasks():
    return api("/api/tasks").get("tasks", [])


def _instance_workload(inst, tasks):
    """Return workload as 0-100 percentage based on workload field + in-progress tasks."""
    base = inst.get("workload", 0)
    in_progress = len([t for t in tasks if t.get("assignee") == inst.get("id")
                        and t.get("status") == "in_progress"])
    # blend: base workload (0-100) + 10 per in-progress task, capped at 100
    return min(100, base + in_progress * 10)


def run_cycle():
    instances = _get_instances()
    online = [i for i in instances if i.get("online")]
    if not online:
        return

    tasks = _get_tasks()
    loads = {i.get("id"): _instance_workload(i, tasks) for i in online}

    # Find overloaded (>80%) and underloaded (<20%)
    overloaded = [i for i in online if loads[i.get("id")] > 80]
    underloaded = [i for i in online if loads[i.get("id")] < 20]

    for over in overloaded:
        if not underloaded:
            break
        under = underloaded[0]
        over_id = over.get("id")
        under_id = under.get("id")
        # Find a movable pending task from overloaded instance
        movable = [t for t in tasks if t.get("assignee") == over_id
                    and t.get("status") == "pending"]
        if movable:
            task = movable[0]
            api("/api/tasks", "POST", {
                "action": "assign",
                "task_id": task.get("id"),
                "assignee": under_id,
            })
            broadcast(f"[LOAD BALANCER] Moved task {task.get('id')} from "
                      f"{over_id} ({loads[over_id]}%) to {under_id} ({loads[under_id]}%)")
            print(f"[{AGENT_ID}] rebalanced: {over_id} -> {under_id} task {task.get('id')}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "load_report":
        instances = _get_instances()
        tasks = _get_tasks()
        online = [i for i in instances if i.get("online")]
        if not online:
            send(sender, "No online instances.")
            return
        lines = ["Load Report:"]
        for inst in online:
            iid = inst.get("id", "?")
            load = _instance_workload(inst, tasks)
            task_ct = len([t for t in tasks if t.get("assignee") == iid
                           and t.get("status") != "done"])
            bar = "#" * (load // 10) + "." * (10 - load // 10)
            lines.append(f"  {iid}: [{bar}] {load}% — {task_ct} tasks")
        send(sender, "\n".join(lines))

    elif text == "rebalance_load":
        instances = _get_instances()
        tasks = _get_tasks()
        online = [i for i in instances if i.get("online")]
        if not online:
            send(sender, "No online instances.")
            return
        loads = {i.get("id"): _instance_workload(i, tasks) for i in online}
        avg = sum(loads.values()) / len(loads)
        moved = 0
        for inst in sorted(online, key=lambda i: loads[i.get("id", "")], reverse=True):
            iid = inst.get("id", "")
            if loads[iid] <= avg + 20:
                continue
            # Find underloaded target
            target = min(online, key=lambda i: loads[i.get("id", "")])
            tid_target = target.get("id", "")
            if tid_target == iid:
                continue
            pending = [t for t in tasks if t.get("assignee") == iid
                        and t.get("status") == "pending"]
            if pending:
                task = pending[0]
                api("/api/tasks", "POST", {
                    "action": "assign",
                    "task_id": task.get("id"),
                    "assignee": tid_target,
                })
                loads[iid] -= 10
                loads[tid_target] += 10
                moved += 1
        send(sender, f"Rebalance complete: {moved} task(s) moved. Target average: {round(avg, 1)}%.")

    elif text.startswith("capacity "):
        inst_id = text[len("capacity "):].strip()
        instances = _get_instances()
        tasks = _get_tasks()
        inst = next((i for i in instances if i.get("id") == inst_id), None)
        if not inst:
            send(sender, f"Instance '{inst_id}' not found.")
            return
        load = _instance_workload(inst, tasks)
        remaining = max(0, 100 - load)
        approx_tasks = remaining // 10
        send(sender, f"Instance '{inst_id}': load={load}%, remaining capacity={remaining}%, "
                     f"~{approx_tasks} more tasks can be handled.")


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
