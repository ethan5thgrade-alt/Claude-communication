#!/usr/bin/env python3
"""
Agent 014 — Message Deduplicator
Role: Detects and prevents duplicate message delivery.
Listens for: dedup_stats, check_duplicate <text>
Emits: dedup alerts to system when duplicates found
"""
import os
import sys
import json
import time
import hashlib
import requests
import threading
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_014_message_deduplicator"
AGENT_NAME = "Agent 014 — Message Deduplicator"
ROOM = os.environ.get("MESH_ROOM", "system")

DEDUP_WINDOW = 60  # seconds — messages within this window from same sender are considered duplicates

_lock = threading.Lock()
# fingerprint -> list of (timestamp, sender) pairs
_fingerprint_map: dict = defaultdict(list)
_seen_msg_ids: set = set()
_dedup_count = 0
_total_checked = 0


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _make_fingerprint(text: str, sender: str) -> str:
    """Create a fingerprint for deduplication."""
    normalized = text.strip().lower()
    content = f"{sender}:{normalized}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _is_duplicate(text: str, sender: str, timestamp: float) -> bool:
    """Return True if this message appears to be a duplicate within the window."""
    fp = _make_fingerprint(text, sender)
    cutoff = timestamp - DEDUP_WINDOW
    with _lock:
        occurrences = _fingerprint_map.get(fp, [])
        # Check if same content+sender within window
        recent = [t for t, s in occurrences if t > cutoff and s == sender]
        if recent:
            return True
        # Record this occurrence
        _fingerprint_map[fp].append((timestamp, sender))
        # Prune old entries from this fingerprint
        _fingerprint_map[fp] = [(t, s) for t, s in _fingerprint_map[fp] if t > cutoff]
    return False


def _cleanup_old_fingerprints():
    """Remove fingerprints with no recent entries."""
    cutoff = time.time() - DEDUP_WINDOW
    with _lock:
        to_delete = []
        for fp, entries in _fingerprint_map.items():
            remaining = [(t, s) for t, s in entries if t > cutoff]
            if remaining:
                _fingerprint_map[fp] = remaining
            else:
                to_delete.append(fp)
        for fp in to_delete:
            del _fingerprint_map[fp]


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "dedup_stats":
        with _lock:
            fp_count = len(_fingerprint_map)
        reply = json.dumps({
            "duplicates_caught": _dedup_count,
            "total_checked": _total_checked,
            "active_fingerprints": fp_count,
            "dedup_window_seconds": DEDUP_WINDOW,
            "dedup_rate": round(_dedup_count / _total_checked, 4) if _total_checked > 0 else 0,
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("check_duplicate "):
        check_text = text[len("check_duplicate "):].strip()
        is_dup = _is_duplicate(check_text, sender, time.time())
        reply = json.dumps({
            "text_preview": check_text[:100],
            "is_duplicate": is_dup,
            "window_seconds": DEDUP_WINDOW,
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _dedup_count, _total_checked
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    duplicates_found = []
    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)

        text = msg.get("text", "")
        sender = msg.get("from", "unknown")
        ts_str = msg.get("ts", "")

        # Parse timestamp
        try:
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = time.time()

        _total_checked += 1
        if _is_duplicate(text, sender, ts):
            _dedup_count += 1
            duplicates_found.append({
                "msg_id": msg_id,
                "from": sender,
                "text_preview": text[:80],
            })

    if duplicates_found:
        print(f"[{AGENT_ID}] detected {len(duplicates_found)} duplicate messages")
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({
                    "event": "duplicates_detected",
                    "count": len(duplicates_found),
                    "samples": duplicates_found[:3],
                }),
                "from": AGENT_ID,
            })
        except Exception:
            pass

    # Periodically clean up
    _cleanup_old_fingerprints()

    # Prune seen IDs
    if len(_seen_msg_ids) > 10000:
        to_remove = list(_seen_msg_ids)[:5000]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)

    print(f"[{AGENT_ID}] checked {_total_checked} total, caught {_dedup_count} duplicates")


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
