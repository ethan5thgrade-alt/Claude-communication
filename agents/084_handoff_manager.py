#!/usr/bin/env python3
"""Agent 084 — Handoff Manager
Role: Manages smooth task handoffs between Claude instances.
"""
import os, sys, json, time, requests, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_084_handoff_manager"
AGENT_NAME = "Agent 084 — Handoff Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# handoff_id -> {task_id, from, to, context, ts, acknowledged}
_handoff_log = {}
_handoff_counter = 0


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


def _next_handoff_id():
    global _handoff_counter
    _handoff_counter += 1
    return f"handoff_{_handoff_counter:04d}"


def handle_message(msg):
    global _handoff_log
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("handoff "):
        # handoff <task_id> <from_instance> <to_instance> <context>
        parts = text[len("handoff "):].strip().split(" ", 3)
        if len(parts) < 4:
            send(sender, "Usage: handoff <task_id> <from_instance> <to_instance> <context>")
            return
        task_id, from_inst, to_inst, ctx = parts
        hid = _next_handoff_id()
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Write context to memory
        api("/api/memory", "POST", {
            "key": f"handoff_{hid}_context",
            "value": ctx,
            "type": "handoff",
        })

        # Update task assignee
        api("/api/tasks", "POST", {
            "action": "assign",
            "task_id": task_id,
            "assignee": to_inst,
        })

        # Notify receiving instance
        send(to_inst, f"[HANDOFF {hid}] You are now assigned task {task_id}. "
                      f"From: {from_inst}. Context: {ctx}")

        _handoff_log[hid] = {
            "task_id": task_id,
            "from": from_inst,
            "to": to_inst,
            "context": ctx,
            "ts": ts,
            "acknowledged": False,
        }
        send(sender, f"Handoff {hid} initiated: {task_id} from {from_inst} to {to_inst}.")

    elif text == "handoff_status":
        if not _handoff_log:
            send(sender, "No handoffs recorded.")
            return
        lines = ["Recent Handoffs:"]
        for hid, info in list(_handoff_log.items())[-20:]:
            ack = "ACK" if info.get("acknowledged") else "pending"
            lines.append(f"  {hid}: task={info['task_id']} {info['from']} -> {info['to']} [{ack}]")
        send(sender, "\n".join(lines))

    elif text.startswith("request_handoff "):
        task_id = text[len("request_handoff "):].strip()
        instances = _get_instances()
        online = [i for i in instances if i.get("online") and i.get("id") != sender]
        if not online:
            send(sender, "No other online instances available for handoff.")
            return
        # Pick least-loaded
        tasks = _get_tasks()
        def task_count(inst):
            return len([t for t in tasks if t.get("assignee") == inst.get("id") and
                         t.get("status") != "done"])
        target = min(online, key=task_count)
        send(target.get("id"), f"[HANDOFF REQUEST] Can you accept task {task_id} from {sender}? "
                               f"Reply: accept_handoff {task_id}")
        send(sender, f"Handoff request for {task_id} sent to {target.get('id')}.")

    elif text.startswith("accept_handoff "):
        task_id = text[len("accept_handoff "):].strip()
        # Find matching pending handoff and mark acknowledged
        for hid, info in _handoff_log.items():
            if info["task_id"] == task_id and info["to"] == sender:
                info["acknowledged"] = True
                send(info["from"], f"Handoff {hid} acknowledged by {sender}.")
                send(sender, f"Handoff {hid} accepted. You are now responsible for task {task_id}.")
                print(f"[{AGENT_ID}] handoff {hid} acknowledged by {sender}")
                return
        send(sender, f"No pending handoff found for task {task_id} to you.")


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
            pass  # no periodic cycle needed
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
