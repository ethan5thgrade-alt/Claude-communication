#!/usr/bin/env python3
"""
Agent 003 — Connection Health Monitor
Role: Pings all instances, detects and reports dead connections.
Listens for: ping, instance_health_report
Emits: alert to system room when instance is missing >2 cycles
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
AGENT_ID = "agent_003_connection_health_monitor"
AGENT_NAME = "Agent 003 — Connection Health Monitor"
ROOM = os.environ.get("MESH_ROOM", "system")

# per-instance tracking: id -> {"seen": bool, "missing_cycles": int, "first_seen": ts, "last_seen": ts, "history": []}
_instance_stats: dict = {}
_lock = threading.Lock()
_cycle_interval = 60  # seconds


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

    if text == "ping":
        ts_sent = time.time()
        reply = json.dumps({"status": "pong", "latency_ms": 0, "ts": ts_sent})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "instance_health_report":
        with _lock:
            report = {}
            for iid, stats in _instance_stats.items():
                report[iid] = {
                    "first_seen": stats.get("first_seen"),
                    "last_seen": stats.get("last_seen"),
                    "missing_cycles": stats.get("missing_cycles", 0),
                    "status": "offline" if stats.get("missing_cycles", 0) >= 2 else "online",
                    "uptime_estimate_s": (
                        (stats.get("last_seen", 0) - stats.get("first_seen", 0))
                        if stats.get("first_seen") else 0
                    ),
                }
        reply = json.dumps({"health_report": report, "total_tracked": len(report)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    try:
        result = get("/api/instances")
        instances_list = result.get("instances", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error fetching instances: {e}")
        return

    now = time.time()
    current_ids = {inst["id"] for inst in instances_list if "id" in inst}

    with _lock:
        # Update stats for currently seen instances
        for inst in instances_list:
            iid = inst.get("id")
            if not iid:
                continue
            if iid not in _instance_stats:
                _instance_stats[iid] = {
                    "first_seen": now,
                    "last_seen": now,
                    "missing_cycles": 0,
                    "history": [],
                }
            else:
                _instance_stats[iid]["last_seen"] = now
                _instance_stats[iid]["missing_cycles"] = 0
            _instance_stats[iid]["history"].append({"ts": now, "status": "online"})
            # Keep last 100 history entries
            _instance_stats[iid]["history"] = _instance_stats[iid]["history"][-100:]

        # Check instances that are now missing
        alerted = []
        for iid in list(_instance_stats.keys()):
            if iid not in current_ids and iid != AGENT_ID:
                _instance_stats[iid]["missing_cycles"] = _instance_stats[iid].get("missing_cycles", 0) + 1
                _instance_stats[iid]["history"].append({"ts": now, "status": "offline"})
                _instance_stats[iid]["history"] = _instance_stats[iid]["history"][-100:]
                mc = _instance_stats[iid]["missing_cycles"]
                if mc >= 2:
                    alerted.append((iid, mc))

    for iid, mc in alerted:
        print(f"[{AGENT_ID}] ALERT: {iid} missing for {mc} cycles")
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({
                    "event": "instance_alert",
                    "instance_id": iid,
                    "missing_cycles": mc,
                    "message": f"Instance {iid} has been offline for {mc} monitor cycles",
                }),
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
        time.sleep(_cycle_interval)


if __name__ == "__main__":
    main()
