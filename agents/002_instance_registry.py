#!/usr/bin/env python3
"""
Agent 002 — Instance Registry
Role: Tracks all connected instances, maintains a live directory.
Listens for: who_is_online, find_agent <capability>
Emits: instance_joined, instance_left broadcasts
"""
import os
import sys
import json
import time
import requests
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_002_instance_registry"
AGENT_NAME = "Agent 002 — Instance Registry"
ROOM = os.environ.get("MESH_ROOM", "system")

_snapshot: dict = {}   # id -> instance info
_lock = threading.Lock()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "who_is_online":
        with _lock:
            snap = dict(_snapshot)
        rooms: dict = {}
        for iid, info in snap.items():
            room = info.get("room", "default")
            rooms.setdefault(room, []).append(iid)
        reply = json.dumps({
            "instances": list(snap.values()),
            "rooms": rooms,
            "total": len(snap),
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("find_agent "):
        capability = text[len("find_agent "):].strip().lower()
        with _lock:
            snap = dict(_snapshot)
        matches = []
        for iid, info in snap.items():
            name = info.get("name", "").lower()
            role = info.get("role", "").lower()
            if capability in name or capability in role or capability in iid.lower():
                matches.append({"id": iid, "name": info.get("name", ""), "room": info.get("room", "")})
        reply = json.dumps({"capability": capability, "matches": matches})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _snapshot
    try:
        result = get("/api/instances")
        instances_list = result.get("instances", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error fetching instances: {e}")
        return

    new_snap = {inst["id"]: inst for inst in instances_list if "id" in inst}

    with _lock:
        old_snap = dict(_snapshot)
        _snapshot = new_snap

    old_ids = set(old_snap.keys())
    new_ids = set(new_snap.keys())

    for iid in new_ids - old_ids:
        info = new_snap[iid]
        print(f"[{AGENT_ID}] instance_joined: {iid} ({info.get('name', '')})")
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({"event": "instance_joined", "id": iid, "name": info.get("name", ""), "room": info.get("room", "")}),
                "from": AGENT_ID,
            })
        except Exception:
            pass

    for iid in old_ids - new_ids:
        info = old_snap[iid]
        print(f"[{AGENT_ID}] instance_left: {iid} ({info.get('name', '')})")
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({"event": "instance_left", "id": iid, "name": info.get("name", ""), "room": info.get("room", "")}),
                "from": AGENT_ID,
            })
        except Exception:
            pass


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    connect.start()
    connect.on_message(handle_message)

    print(f"[{AGENT_ID}] online")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(15)


if __name__ == "__main__":
    main()
