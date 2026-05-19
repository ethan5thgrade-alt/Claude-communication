#!/usr/bin/env python3
"""Agent 038 — Memory Sync Agent
Role: Syncs critical memories across all instances in the room.
Listens for: sync_to_room <key>, sync_all_contracts, sync_status
Emits: memory broadcasts to all room members
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_038_memory_sync_agent"
AGENT_NAME = "Agent 038 — Memory Sync Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 300  # 5 minutes

# Track acknowledgements: key -> set of instance_ids that received it
_ack_log = {}


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


def get_memory():
    result = api("/api/memory")
    if isinstance(result, list):
        return result
    return result.get("memory", []) if isinstance(result, dict) else []


def get_instances():
    result = api("/api/instances")
    return result.get("instances", []) if isinstance(result, dict) else []


def sync_entry_to_room(entry):
    """Broadcast a memory entry to all online instances."""
    key = entry.get("key", "")
    value = entry.get("value", "")
    mem_type = entry.get("type", "contract")
    payload = json.dumps({"sync": True, "key": key, "value": value, "type": mem_type})
    broadcast(f"[memory_sync] CONTRACT: {payload}")

    # Track which instances are online (they'll receive it)
    instances = get_instances()
    online_ids = {i.get("id") for i in instances if i.get("online")}
    if key not in _ack_log:
        _ack_log[key] = set()
    _ack_log[key].update(online_ids)


def run_cycle():
    entries = get_memory()
    contracts = [e for e in entries if e.get("type") == "contract"]

    for entry in contracts:
        sync_entry_to_room(entry)

    print(f"[{AGENT_ID}] synced {len(contracts)} contract memories to room")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("sync_to_room "):
        key = text.split(" ", 1)[1].strip()
        entries = get_memory()
        entry = next((e for e in entries if e.get("key") == key), None)
        if not entry:
            send(sender, f"memory key '{key}' not found")
            return
        sync_entry_to_room(entry)
        send(sender, f"memory '{key}' broadcast to all room members")

    elif text == "sync_all_contracts":
        entries = get_memory()
        contracts = [e for e in entries if e.get("type") == "contract"]
        for entry in contracts:
            sync_entry_to_room(entry)
        send(sender, f"synced {len(contracts)} contract memories to all instances")

    elif text == "sync_status":
        status = {}
        for key, instance_set in _ack_log.items():
            status[key] = list(instance_set)
        send(sender, json.dumps({"synced_keys": status}))


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
