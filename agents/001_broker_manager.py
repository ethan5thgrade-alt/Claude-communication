#!/usr/bin/env python3
"""
Agent 001 — Broker Manager
Role: Monitors broker health, restarts it if it goes down.
Listens for: restart_broker, broker_status
Emits: broker_restarted broadcast, broker_status reply
"""
import os
import sys
import json
import time
import subprocess
import requests
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_001_broker_manager"
AGENT_NAME = "Agent 001 — Broker Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
BROKER_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "broker.py")

_fail_count = 0
_broker_proc = None
_start_time = time.time()
_lock = threading.Lock()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _spawn_broker():
    global _broker_proc, _start_time
    with _lock:
        if _broker_proc and _broker_proc.poll() is None:
            return  # already running
        print(f"[{AGENT_ID}] spawning broker.py …")
        _broker_proc = subprocess.Popen(
            [sys.executable, BROKER_PY],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _start_time = time.time()
        print(f"[{AGENT_ID}] broker spawned, pid={_broker_proc.pid}")


def _wait_for_broker(timeout=30):
    """Poll /api/health until the broker responds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{BROKER_HTTP}/api/health", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "restart_broker":
        print(f"[{AGENT_ID}] restart_broker requested by {sender}")
        with _lock:
            if _broker_proc and _broker_proc.poll() is None:
                _broker_proc.terminate()
                _broker_proc.wait(timeout=10)
        _spawn_broker()
        recovered = _wait_for_broker()
        reply = "broker restarted and healthy" if recovered else "broker restarted but health check failed"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
            post("/api/send", {"to": "system", "text": f"broker restarted by {sender}", "from": AGENT_ID})
        except Exception:
            pass

    elif text == "broker_status":
        try:
            health = get("/api/health")
            instances = get("/api/instances")
            online_count = len([i for i in instances.get("instances", []) if i.get("online")])
            uptime = health.get("uptime_seconds", 0)
            build_sha = health.get("build_sha", "unknown")
            reply = json.dumps({
                "uptime_seconds": uptime,
                "online_count": online_count,
                "build_sha": build_sha,
                "agent_uptime": time.time() - _start_time,
            })
        except Exception as e:
            reply = f"error fetching broker status: {e}"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _fail_count
    try:
        r = requests.get(f"{BROKER_HTTP}/api/health", timeout=5)
        if r.status_code == 200:
            _fail_count = 0
            print(f"[{AGENT_ID}] broker healthy (uptime={r.json().get('uptime_seconds', '?')}s)")
        else:
            _fail_count += 1
            print(f"[{AGENT_ID}] broker health returned {r.status_code} (fail #{_fail_count})")
    except Exception as e:
        _fail_count += 1
        print(f"[{AGENT_ID}] broker health check failed: {e} (fail #{_fail_count})")

    if _fail_count >= 3:
        print(f"[{AGENT_ID}] 3 consecutive failures — restarting broker")
        _spawn_broker()
        recovered = _wait_for_broker()
        _fail_count = 0
        if recovered:
            try:
                post("/api/send", {"to": "system", "text": "broker restarted after 3 consecutive failures", "from": AGENT_ID})
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
        time.sleep(30)


if __name__ == "__main__":
    main()
