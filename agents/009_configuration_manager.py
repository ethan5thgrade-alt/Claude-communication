#!/usr/bin/env python3
"""
Agent 009 — Configuration Manager
Role: Manages system configuration (tokens, ports, settings).
Listens for: get_config, set_room <name>, rotate_token
Emits: config warning broadcasts, token rotation notifications
"""
import os
import sys
import json
import time
import secrets
import requests
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_009_configuration_manager"
AGENT_NAME = "Agent 009 — Configuration Manager"
ROOM = os.environ.get("MESH_ROOM", "system")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_PATH = Path.home() / ".agent-mesh-inbox" / ".mesh_token"

_lock = threading.Lock()
_current_room = ROOM
_warned_no_token = False


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _get_safe_config() -> dict:
    """Return config info without exposing secrets."""
    return {
        "broker_url_http": BROKER_HTTP,
        "broker_url_ws": os.environ.get("BROKER_URL", "ws://localhost:8766"),
        "ui_port": 8765,
        "instance_port": 8766,
        "current_room": _current_room,
        "mesh_token_set": bool(os.environ.get("MESH_TOKEN")),
        "token_file_exists": TOKEN_PATH.exists(),
        "agent_id": AGENT_ID,
    }


def _check_broker_reachable() -> bool:
    try:
        r = requests.get(f"{BROKER_HTTP}/api/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _generate_token() -> str:
    return secrets.token_hex(32)


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "get_config":
        config = _get_safe_config()
        reply = json.dumps(config)
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("set_room "):
        global _current_room
        new_room = text[len("set_room "):].strip()
        if not new_room:
            reply = "error: room name cannot be empty"
        else:
            with _lock:
                _current_room = new_room
            os.environ["MESH_ROOM"] = new_room
            reply = f"default room updated to: {new_room}"
            print(f"[{AGENT_ID}] room changed to {new_room}")
            try:
                post("/api/send", {
                    "to": "system",
                    "text": json.dumps({"event": "room_changed", "new_room": new_room, "by": sender}),
                    "from": AGENT_ID,
                })
            except Exception:
                pass
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "rotate_token":
        new_token = _generate_token()
        # Save to token file
        try:
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(new_token)
            os.environ["MESH_TOKEN"] = new_token
            reply = f"token rotated. New token saved to {TOKEN_PATH}. Restart agents to apply."
            print(f"[{AGENT_ID}] token rotated by {sender}")
            # Notify all instances
            try:
                post("/api/send", {
                    "to": "system",
                    "text": json.dumps({
                        "event": "token_rotated",
                        "by": sender,
                        "token_file": str(TOKEN_PATH),
                        "note": "Restart all agents to apply the new token",
                    }),
                    "from": AGENT_ID,
                })
            except Exception:
                pass
        except Exception as e:
            reply = f"token rotation failed: {e}"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _warned_no_token

    # Check MESH_TOKEN
    token = os.environ.get("MESH_TOKEN")
    if not token and not _warned_no_token:
        print(f"[{AGENT_ID}] WARNING: MESH_TOKEN not set — connections are unauthenticated")
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({
                    "event": "config_warning",
                    "message": "MESH_TOKEN is not set — mesh is operating without authentication",
                }),
                "from": AGENT_ID,
            })
        except Exception:
            pass
        _warned_no_token = True
    elif token:
        _warned_no_token = False

    # Check broker ports
    if not _check_broker_reachable():
        print(f"[{AGENT_ID}] WARNING: broker not reachable at {BROKER_HTTP}")
    else:
        print(f"[{AGENT_ID}] broker reachable, config OK")

    # Check if connect.py can reach broker
    try:
        health = get("/api/health")
        if health.get("status") == "ok":
            print(f"[{AGENT_ID}] broker health OK: uptime={health.get('uptime_seconds', '?')}s")
    except Exception as e:
        print(f"[{AGENT_ID}] broker health check failed: {e}")


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
        time.sleep(300)  # every 5 minutes


if __name__ == "__main__":
    main()
