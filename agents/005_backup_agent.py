#!/usr/bin/env python3
"""
Agent 005 — Backup Agent
Role: Creates dated backups of state.json every hour.
Listens for: backup_now, list_backups, restore_backup <filename>
Emits: backup confirmation replies
"""
import os
import sys
import json
import time
import shutil
import glob
import requests
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_005_backup_agent"
AGENT_NAME = "Agent 005 — Backup Agent"
ROOM = os.environ.get("MESH_ROOM", "system")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "state.json")
BACKUPS_DIR = os.path.join(ROOT, "backups")
MAX_BACKUPS = 24
_last_backup_time = 0.0
_lock = threading.Lock()

# pending restore confirmations: sender -> filename
_pending_restores: dict = {}


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _make_backup() -> str:
    """Creates a timestamped backup. Returns path or raises."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUPS_DIR, f"state_{ts}.json")
    shutil.copy(STATE_PATH, dest)
    return dest


def _prune_backups():
    """Keep only the newest MAX_BACKUPS backups."""
    backups = sorted(glob.glob(os.path.join(BACKUPS_DIR, "state_*.json")))
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        try:
            os.remove(oldest)
            print(f"[{AGENT_ID}] pruned old backup: {oldest}")
        except Exception as e:
            print(f"[{AGENT_ID}] prune error: {e}")


def _list_backups() -> list:
    backups = sorted(glob.glob(os.path.join(BACKUPS_DIR, "state_*.json")), reverse=True)
    result = []
    for bp in backups:
        try:
            size = os.path.getsize(bp)
        except Exception:
            size = -1
        result.append({"filename": os.path.basename(bp), "size_bytes": size, "path": bp})
    return result


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "backup_now":
        try:
            with _lock:
                path = _make_backup()
                _prune_backups()
            reply = json.dumps({"status": "ok", "path": path, "ts": datetime.now().isoformat()})
        except Exception as e:
            reply = json.dumps({"status": "error", "message": str(e)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "list_backups":
        with _lock:
            backups = _list_backups()
        reply = json.dumps({"backups": backups, "count": len(backups)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("restore_backup "):
        filename = text[len("restore_backup "):].strip()
        # Check for confirmation token
        if text.endswith(" CONFIRMED"):
            filename = filename.replace(" CONFIRMED", "").strip()
            backup_path = os.path.join(BACKUPS_DIR, filename)
            if not os.path.exists(backup_path):
                reply = f"backup not found: {filename}"
            else:
                try:
                    with _lock:
                        shutil.copy(backup_path, STATE_PATH)
                    reply = f"restored from {filename}"
                except Exception as e:
                    reply = f"restore failed: {e}"
        else:
            # Store pending restore, ask for confirmation
            _pending_restores[sender] = filename
            backup_path = os.path.join(BACKUPS_DIR, filename)
            if not os.path.exists(backup_path):
                reply = f"backup not found: {filename}"
            else:
                size = os.path.getsize(backup_path)
                reply = (
                    f"CONFIRM: restore {filename} ({size} bytes) to state.json? "
                    f"Send: restore_backup {filename} CONFIRMED"
                )
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _last_backup_time
    now = time.time()
    # Backup every hour
    if now - _last_backup_time >= 3600:
        if os.path.exists(STATE_PATH):
            try:
                with _lock:
                    path = _make_backup()
                    _prune_backups()
                _last_backup_time = now
                print(f"[{AGENT_ID}] hourly backup created: {path}")
            except Exception as e:
                print(f"[{AGENT_ID}] backup failed: {e}")
        else:
            print(f"[{AGENT_ID}] state.json does not exist, skipping backup")


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    connect.start()
    connect.on_message(handle_message)

    print(f"[{AGENT_ID}] online")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
