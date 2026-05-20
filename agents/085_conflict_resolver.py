#!/usr/bin/env python3
"""Agent 085 — Conflict Resolver
Role: Detects and resolves conflicts when multiple Claude instances work on the same thing.
"""
import os, sys, json, time, requests, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_085_conflict_resolver"
AGENT_NAME = "Agent 085 — Conflict Resolver"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# resource -> [instances that mentioned it recently]
_resource_mentions = {}
# resource -> {instance1, instance2, ts, status}
_conflicts = {}
_recent_messages = []  # last 200 messages scanned
MAX_SCAN = 200


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


def _scan_messages_for_conflicts():
    """Look for same file/task/resource mentioned by multiple different instances."""
    data = api("/api/status")
    messages = data.get("messages", [])[-MAX_SCAN:]

    # Reset mentions (sliding window)
    resource_to_senders = {}
    for m in messages:
        sender = m.get("from", "")
        text = m.get("text", "")
        if not sender or sender in (AGENT_ID, "all"):
            continue
        # Simple heuristic: look for tokens that look like file paths or task IDs
        import re
        resources = re.findall(r'[\w./\-]+\.(py|js|ts|json|md|sh|yaml|yml)', text)
        resources += re.findall(r'task_\w+', text)
        for resource in resources:
            resource_to_senders.setdefault(resource, set()).add(sender)

    # Detect conflicts: same resource, 2+ different senders
    for resource, senders in resource_to_senders.items():
        if len(senders) >= 2:
            sender_list = sorted(senders)
            key = resource
            if key not in _conflicts:
                inst1, inst2 = sender_list[0], sender_list[1]
                ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                _conflicts[key] = {"resource": resource, "instance1": inst1,
                                   "instance2": inst2, "ts": ts, "status": "detected"}
                broadcast(f"[CONFLICT DETECTED] resource='{resource}' claimed by "
                          f"{inst1} and {inst2}. Mediating...")
                # Notify both
                send(inst1, f"[CONFLICT] You and {inst2} are both working on '{resource}'. "
                            f"Please pause and coordinate. Agent 085 mediating.")
                send(inst2, f"[CONFLICT] You and {inst1} are both working on '{resource}'. "
                            f"Please pause and coordinate. Agent 085 mediating.")
                print(f"[{AGENT_ID}] conflict detected: {resource} between {inst1} and {inst2}")


def run_cycle():
    _scan_messages_for_conflicts()


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("conflict_detected "):
        # conflict_detected <resource> <instance1> <instance2>
        parts = text[len("conflict_detected "):].strip().split()
        if len(parts) < 3:
            send(sender, "Usage: conflict_detected <resource> <instance1> <instance2>")
            return
        resource, inst1, inst2 = parts[0], parts[1], parts[2]
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _conflicts[resource] = {"resource": resource, "instance1": inst1,
                                 "instance2": inst2, "ts": ts, "status": "formal"}
        send(inst1, f"[CONFLICT PAUSE] Pause work on '{resource}'. Conflict with {inst2}. Awaiting resolution.")
        send(inst2, f"[CONFLICT PAUSE] Pause work on '{resource}'. Conflict with {inst1}. Awaiting resolution.")
        send(sender, f"Conflict on '{resource}' formally registered. Both instances notified to pause.")

    elif text.startswith("resolve "):
        # resolve <resource> <winner>
        parts = text[len("resolve "):].strip().split()
        if len(parts) < 2:
            send(sender, "Usage: resolve <resource> <winner>")
            return
        resource, winner = parts[0], parts[1]
        conflict = _conflicts.get(resource)
        if not conflict:
            send(sender, f"No known conflict for '{resource}'.")
            return
        loser = conflict["instance1"] if conflict["instance2"] == winner else conflict["instance2"]
        conflict["status"] = "resolved"
        send(winner, f"[RESOLVED] You are the owner of '{resource}'. Proceed.")
        send(loser, f"[RESOLVED] Stand down on '{resource}'. {winner} is the owner.")
        send(sender, f"Conflict on '{resource}' resolved. Winner: {winner}.")

    elif text.startswith("merge_outputs "):
        task_id = text[len("merge_outputs "):].strip()
        tasks = api("/api/tasks").get("tasks", [])
        matching = [t for t in tasks if t.get("id") == task_id]
        if not matching:
            send(sender, f"Task {task_id} not found.")
            return
        task = matching[0]
        result = task.get("result", "")
        send(sender, f"Task {task_id} output collected. Result: {result}\n"
                     f"Manual merge required — review both instance outputs and combine.")


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
