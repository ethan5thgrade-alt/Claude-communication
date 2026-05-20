#!/usr/bin/env python3
"""
Agent 004 — State Persistence Manager
Role: Manages state.json integrity — detects corruption, triggers backups.
Listens for: state_stats, compact_state
Emits: state health alerts to system room
"""
import os
import sys
import json
import time
import shutil
import glob
import requests
import threading
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_004_state_persistence_manager"
AGENT_NAME = "Agent 004 — State Persistence Manager"
ROOM = os.environ.get("MESH_ROOM", "system")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "state.json")
BACKUPS_DIR = os.path.join(ROOT, "backups")
REQUIRED_KEYS = {"instances_meta", "messages", "tasks", "memory", "teams"}

_lock = threading.Lock()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _read_state() -> tuple:
    """Returns (state_dict_or_None, error_str_or_None)."""
    if not os.path.exists(STATE_PATH):
        return None, "state.json does not exist"
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
        return data, None
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {e}"
    except Exception as e:
        return None, f"Read error: {e}"


def _validate_state(data: dict) -> list:
    """Returns list of issues. Empty list = valid."""
    issues = []
    if not isinstance(data, dict):
        issues.append("state is not a dict")
        return issues
    for key in REQUIRED_KEYS:
        if key not in data:
            issues.append(f"missing required key: {key}")
    return issues


def _find_latest_backup() -> str | None:
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    backups = sorted(glob.glob(os.path.join(BACKUPS_DIR, "state_*.json")))
    return backups[-1] if backups else None


def _restore_from_backup(backup_path: str) -> bool:
    try:
        shutil.copy(backup_path, STATE_PATH)
        print(f"[{AGENT_ID}] restored state from {backup_path}")
        return True
    except Exception as e:
        print(f"[{AGENT_ID}] restore failed: {e}")
        return False


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "state_stats":
        with _lock:
            state, err = _read_state()
        if err:
            reply = json.dumps({"error": err})
        else:
            size_bytes = os.path.getsize(STATE_PATH) if os.path.exists(STATE_PATH) else 0
            reply = json.dumps({
                "size_bytes": size_bytes,
                "message_count": len(state.get("messages", [])),
                "task_count": len(state.get("tasks", [])),
                "memory_count": len(state.get("memory", [])),
                "audit_count": len(state.get("audit", [])),
                "schema_version": state.get("schema_version", "unknown"),
            })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "compact_state":
        # Remove messages older than 7 days via broker clear (approximate — log the action)
        cutoff = time.time() - (7 * 24 * 3600)
        with _lock:
            state, err = _read_state()
        if err:
            reply = f"Cannot compact: {err}"
        else:
            before = len(state.get("messages", []))
            filtered = [m for m in state.get("messages", []) if _parse_ts(m.get("ts", "")) > cutoff]
            removed = before - len(filtered)
            state["messages"] = filtered
            try:
                with open(STATE_PATH, "w") as f:
                    json.dump(state, f, default=str)
                reply = f"compacted: removed {removed} messages older than 7 days"
            except Exception as e:
                reply = f"compact failed: {e}"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def _parse_ts(ts_str: str) -> float:
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def run_cycle():
    with _lock:
        state, err = _read_state()

    if err:
        print(f"[{AGENT_ID}] state.json error: {err}")
        backup = _find_latest_backup()
        if backup:
            with _lock:
                _restore_from_backup(backup)
            try:
                post("/api/send", {
                    "to": "system",
                    "text": json.dumps({"event": "state_restored", "from_backup": backup, "reason": err}),
                    "from": AGENT_ID,
                })
            except Exception:
                pass
        return

    issues = _validate_state(state)
    size_bytes = os.path.getsize(STATE_PATH) if os.path.exists(STATE_PATH) else 0
    print(f"[{AGENT_ID}] state.json OK — {size_bytes} bytes, {len(state.get('messages', []))} messages")

    if issues:
        print(f"[{AGENT_ID}] state validation issues: {issues}")
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({"event": "state_validation_issues", "issues": issues}),
                "from": AGENT_ID,
            })
        except Exception:
            pass


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
        time.sleep(300)  # every 5 minutes


if __name__ == "__main__":
    main()
