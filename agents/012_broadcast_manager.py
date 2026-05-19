#!/usr/bin/env python3
"""
Agent 012 — Broadcast Manager
Role: Manages broadcasts — prevents spam, batches related broadcasts.
Listens for: broadcast_summary, mute_instance <id> <minutes>
Emits: throttle warnings when spam detected
"""
import os
import sys
import json
import time
import requests
import threading
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_012_broadcast_manager"
AGENT_NAME = "Agent 012 — Broadcast Manager"
ROOM = os.environ.get("MESH_ROOM", "system")

_lock = threading.Lock()
# source_id -> deque of timestamps (last minute)
_broadcast_times: dict = defaultdict(lambda: deque(maxlen=500))
# source_id -> mute_until timestamp
_muted: dict = {}
# Recent broadcasts: deque of (ts, from, text)
_recent_broadcasts: deque = deque(maxlen=100)
_seen_broadcast_ids: set = set()


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

    if text == "broadcast_summary":
        with _lock:
            recent = list(_recent_broadcasts)[-10:]
        reply = json.dumps({
            "last_10_broadcasts": [
                {"ts": ts, "from": frm, "text": txt}
                for ts, frm, txt in recent
            ],
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("mute_instance "):
        parts = text.split()
        if len(parts) >= 3:
            target_id = parts[1]
            try:
                minutes = float(parts[2])
            except ValueError:
                minutes = 5.0
            mute_until = time.time() + minutes * 60
            with _lock:
                _muted[target_id] = mute_until
            reply = f"muted {target_id} for {minutes} minutes"
            print(f"[{AGENT_ID}] {reply}")
        else:
            reply = "usage: mute_instance <instance_id> <minutes>"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def _is_muted(source_id: str) -> bool:
    with _lock:
        mute_until = _muted.get(source_id, 0)
    if mute_until and time.time() < mute_until:
        return True
    if mute_until and time.time() >= mute_until:
        with _lock:
            _muted.pop(source_id, None)
    return False


def run_cycle():
    """Scan status for broadcasts, check for spam."""
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    now = time.time()
    cutoff_1min = now - 60

    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_broadcast_ids:
            continue
        _seen_broadcast_ids.add(msg_id)

        msg_type = msg.get("type", "")
        # Track all broadcast-type messages
        if msg_type in ("broadcast", "message") and msg.get("to") in ("all", "system"):
            source = msg.get("from", "unknown")
            ts = msg.get("ts", "")
            text = msg.get("text", "")

            # Check if muted
            if _is_muted(source):
                print(f"[{AGENT_ID}] suppressing broadcast from muted instance: {source}")
                continue

            with _lock:
                _broadcast_times[source].append(now)
                _recent_broadcasts.append((ts, source, text[:200]))

            # Count recent broadcasts from this source
            with _lock:
                recent_from_source = [t for t in _broadcast_times[source] if t > cutoff_1min]

            rate = len(recent_from_source)
            if rate > 10:
                print(f"[{AGENT_ID}] SPAM DETECTED: {source} sent {rate} broadcasts in last 60s")
                try:
                    post("/api/send", {
                        "to": "system",
                        "text": json.dumps({
                            "event": "broadcast_spam_warning",
                            "source": source,
                            "rate_per_min": rate,
                            "message": f"Instance {source} is broadcasting at {rate}/min — consider muting",
                        }),
                        "from": AGENT_ID,
                    })
                except Exception:
                    pass

    # Prune seen IDs
    if len(_seen_broadcast_ids) > 10000:
        to_remove = list(_seen_broadcast_ids)[:5000]
        for mid in to_remove:
            _seen_broadcast_ids.discard(mid)

    print(f"[{AGENT_ID}] cycle complete — tracking {len(_broadcast_times)} broadcast sources, {len(_muted)} muted")


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
        time.sleep(10)


if __name__ == "__main__":
    main()
