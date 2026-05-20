#!/usr/bin/env python3
"""
Agent 013 — Message Validator
Role: Validates message format and content before routing.
Listens for: validate <json>, validation_report
Emits: validation violation logs to system
"""
import os
import sys
import json
import time
import requests
import threading
from collections import defaultdict, deque
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_013_message_validator"
AGENT_NAME = "Agent 013 — Message Validator"
ROOM = os.environ.get("MESH_ROOM", "system")

MAX_TEXT_BYTES = 10 * 1024  # 10 KB
REQUIRED_FIELDS = {"type"}  # minimum required fields for a message

_lock = threading.Lock()
_seen_msg_ids: set = set()
# violation_type -> deque of timestamps
_violations: dict = defaultdict(lambda: deque(maxlen=1000))
_violation_count = 0


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _validate_payload(payload: dict) -> list:
    """Returns list of validation issues."""
    issues = []

    if not isinstance(payload, dict):
        issues.append("payload is not a dict")
        return issues

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in payload:
            issues.append(f"missing required field: {field}")

    # Text size check
    text = payload.get("text", "")
    if isinstance(text, str) and len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        issues.append(f"text field too large: {len(text.encode('utf-8'))} bytes (max {MAX_TEXT_BYTES})")

    # Type validation
    msg_type = payload.get("type")
    valid_types = {
        "message", "broadcast", "register", "status", "memory_write",
        "task_create", "task_claim", "task_done", "task_status",
        "approval_request", "vote_create", "vote_cast", "log", "typing",
        "plugin_invoke", "heartbeat", "control",
    }
    if msg_type and msg_type not in valid_types:
        issues.append(f"unknown message type: {msg_type}")

    # Check for suspicious content
    if isinstance(text, str):
        if "\x00" in text:
            issues.append("text contains null bytes")
        if len(text) > 0 and text.strip() == "":
            issues.append("text is whitespace-only")

    return issues


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("validate "):
        json_str = text[len("validate "):].strip()
        try:
            payload = json.loads(json_str)
            issues = _validate_payload(payload)
            reply = json.dumps({
                "valid": len(issues) == 0,
                "issues": issues,
                "payload_type": payload.get("type") if isinstance(payload, dict) else "non-dict",
            })
        except json.JSONDecodeError as e:
            reply = json.dumps({"valid": False, "issues": [f"JSON parse error: {e}"]})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "validation_report":
        cutoff = time.time() - 3600
        with _lock:
            report = {}
            for vtype, times in _violations.items():
                recent = [t for t in times if t > cutoff]
                if recent:
                    report[vtype] = len(recent)
        reply = json.dumps({
            "violations_last_hour": report,
            "total_violations": _violation_count,
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _violation_count
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    new_violations = []
    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)

        issues = _validate_payload(msg)
        if issues:
            now = time.time()
            with _lock:
                for issue in issues:
                    vtype = issue.split(":")[0].strip()
                    _violations[vtype].append(now)
                _violation_count += len(issues)
            new_violations.append({
                "msg_id": msg_id,
                "from": msg.get("from", "unknown"),
                "issues": issues,
                "ts": datetime.utcnow().isoformat(),
            })

    if new_violations:
        print(f"[{AGENT_ID}] found {len(new_violations)} messages with validation issues")
        # Log summary to system
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({
                    "event": "validation_violations",
                    "count": len(new_violations),
                    "samples": new_violations[:3],  # first 3 as sample
                }),
                "from": AGENT_ID,
            })
        except Exception:
            pass

    # Prune seen IDs
    if len(_seen_msg_ids) > 10000:
        to_remove = list(_seen_msg_ids)[:5000]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)


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
