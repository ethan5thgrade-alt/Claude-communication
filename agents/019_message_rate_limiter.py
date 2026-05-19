#!/usr/bin/env python3
"""
Agent 019 — Message Rate Limiter
Role: Prevents message flooding, enforces per-instance rate limits.
Listens for: rate_limit_status, set_rate_limit <instance_id> <msgs_per_min>
Emits: rate limit warnings and alerts to system
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
AGENT_ID = "agent_019_message_rate_limiter"
AGENT_NAME = "Agent 019 — Message Rate Limiter"
ROOM = os.environ.get("MESH_ROOM", "system")

DEFAULT_WARN_THRESHOLD = 30   # msgs/min
DEFAULT_ALERT_THRESHOLD = 60  # msgs/min

_lock = threading.Lock()
_seen_msg_ids: set = set()
# instance_id -> deque of timestamps in last 60s
_msg_times: dict = defaultdict(lambda: deque(maxlen=10000))
# custom thresholds: instance_id -> (warn, alert) msgs per minute
_custom_limits: dict = {}
# Track warned/alerted state to avoid repeated notifications
_warned_instances: set = set()
_alerted_instances: set = set()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _get_rate(instance_id: str, window: float = 60.0) -> int:
    """Get message count for instance in the last window seconds."""
    cutoff = time.time() - window
    with _lock:
        times = _msg_times.get(instance_id, deque())
        return sum(1 for t in times if t > cutoff)


def _get_thresholds(instance_id: str) -> tuple:
    """Returns (warn_threshold, alert_threshold) for an instance."""
    with _lock:
        custom = _custom_limits.get(instance_id)
    if custom:
        return custom
    return DEFAULT_WARN_THRESHOLD, DEFAULT_ALERT_THRESHOLD


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "rate_limit_status":
        now = time.time()
        cutoff = now - 60
        with _lock:
            status = {}
            for iid, times in _msg_times.items():
                rate = sum(1 for t in times if t > cutoff)
                warn, alert = _custom_limits.get(iid, (DEFAULT_WARN_THRESHOLD, DEFAULT_ALERT_THRESHOLD))
                status[iid] = {
                    "msgs_per_min": rate,
                    "warn_threshold": warn,
                    "alert_threshold": alert,
                    "status": (
                        "alert" if rate >= alert else
                        "warn" if rate >= warn else
                        "ok"
                    ),
                }
        reply = json.dumps({
            "rate_limits": status,
            "default_warn": DEFAULT_WARN_THRESHOLD,
            "default_alert": DEFAULT_ALERT_THRESHOLD,
        })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("set_rate_limit "):
        parts = text.split()
        if len(parts) >= 3:
            target_id = parts[1]
            try:
                limit = int(parts[2])
                with _lock:
                    _custom_limits[target_id] = (limit, limit * 2)
                reply = f"rate limit set for {target_id}: warn at {limit}/min, alert at {limit * 2}/min"
            except ValueError:
                reply = "invalid value — usage: set_rate_limit <instance_id> <msgs_per_min>"
        else:
            reply = "usage: set_rate_limit <instance_id> <msgs_per_min>"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error: {e}")
        return

    now = time.time()

    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or str(msg)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)

        source = msg.get("from", "unknown")
        if not source or source == AGENT_ID:
            continue

        with _lock:
            _msg_times[source].append(now)

    # Check rates for all tracked instances
    cutoff = now - 60
    warned_this_cycle = set()
    alerted_this_cycle = set()

    with _lock:
        tracked = list(_msg_times.keys())

    for iid in tracked:
        rate = _get_rate(iid)
        warn_threshold, alert_threshold = _get_thresholds(iid)

        if rate >= alert_threshold:
            if iid not in _alerted_instances:
                print(f"[{AGENT_ID}] ALERT: {iid} sending {rate}/min (threshold: {alert_threshold})")
                try:
                    post("/api/send", {
                        "to": "system",
                        "text": json.dumps({
                            "event": "rate_limit_alert",
                            "instance_id": iid,
                            "rate_per_min": rate,
                            "threshold": alert_threshold,
                            "severity": "alert",
                        }),
                        "from": AGENT_ID,
                    })
                except Exception:
                    pass
                _alerted_instances.add(iid)
        elif rate >= warn_threshold:
            if iid not in _warned_instances:
                print(f"[{AGENT_ID}] WARN: {iid} sending {rate}/min (threshold: {warn_threshold})")
                try:
                    post("/api/send", {
                        "to": "system",
                        "text": json.dumps({
                            "event": "rate_limit_warning",
                            "instance_id": iid,
                            "rate_per_min": rate,
                            "threshold": warn_threshold,
                            "severity": "warn",
                        }),
                        "from": AGENT_ID,
                    })
                except Exception:
                    pass
                _warned_instances.add(iid)
        else:
            # Rate returned to normal — clear state
            _warned_instances.discard(iid)
            _alerted_instances.discard(iid)

    # Prune seen IDs
    if len(_seen_msg_ids) > 10000:
        to_remove = list(_seen_msg_ids)[:5000]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)

    print(f"[{AGENT_ID}] tracking {len(_msg_times)} instances")


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
