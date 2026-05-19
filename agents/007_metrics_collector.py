#!/usr/bin/env python3
"""
Agent 007 — Metrics Collector
Role: Tracks system metrics and exposes summaries.
Listens for: metrics_summary, metrics_history <metric> <hours>, alert_threshold <metric> <value>
Emits: alert broadcasts when thresholds exceeded
"""
import os
import sys
import json
import time
import re
import requests
import threading
from collections import deque
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_007_metrics_collector"
AGENT_NAME = "Agent 007 — Metrics Collector"
ROOM = os.environ.get("MESH_ROOM", "system")

# Time-series storage: metric_name -> deque of (timestamp, value)
_series: dict = {}
_series_lock = threading.Lock()
MAX_HISTORY = 24 * 60  # 24h at 1-min resolution

# Alert thresholds: metric_name -> threshold_value
_thresholds: dict = {}
_thresholds_lock = threading.Lock()

# Rolling counters for derived metrics
_message_times: deque = deque(maxlen=1000)
_task_times: deque = deque(maxlen=200)


def get(path, raw=False):
    r = requests.get(f"{BROKER_HTTP}{path}", timeout=5)
    if raw:
        return r.text
    return r.json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _parse_prometheus(text: str) -> dict:
    """Parse Prometheus text format into {metric_name: value} dict."""
    metrics = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # e.g. mesh_messages_total 42
        m = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*(?:\{[^}]*\})?)\s+([\d.eE+\-]+)$', line)
        if m:
            name = re.sub(r'\{[^}]*\}', '', m.group(1))  # strip labels
            try:
                metrics[name] = float(m.group(2))
            except ValueError:
                pass
    return metrics


def _record_metric(name: str, value: float):
    now = time.time()
    with _series_lock:
        if name not in _series:
            _series[name] = deque(maxlen=MAX_HISTORY)
        _series[name].append((now, value))

    # Check threshold
    with _thresholds_lock:
        threshold = _thresholds.get(name)
    if threshold is not None and value > threshold:
        print(f"[{AGENT_ID}] ALERT: {name}={value} exceeds threshold {threshold}")
        try:
            post("/api/send", {
                "to": "system",
                "text": json.dumps({
                    "event": "metric_threshold_exceeded",
                    "metric": name,
                    "value": value,
                    "threshold": threshold,
                    "ts": datetime.utcnow().isoformat(),
                }),
                "from": AGENT_ID,
            })
        except Exception:
            pass


def _messages_per_min() -> float:
    now = time.time()
    cutoff = now - 60
    recent = [t for t in _message_times if t > cutoff]
    return len(recent)


def _tasks_per_hour() -> float:
    now = time.time()
    cutoff = now - 3600
    recent = [t for t in _task_times if t > cutoff]
    return len(recent)


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "metrics_summary":
        with _series_lock:
            summary = {}
            for name, dq in _series.items():
                if dq:
                    vals = [v for _, v in dq]
                    summary[name] = {
                        "latest": vals[-1],
                        "min": min(vals),
                        "max": max(vals),
                        "avg": sum(vals) / len(vals),
                        "count": len(vals),
                    }
        summary["messages_per_min"] = _messages_per_min()
        summary["tasks_per_hour"] = _tasks_per_hour()
        reply = json.dumps(summary)
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("metrics_history "):
        parts = text.split()
        if len(parts) >= 3:
            metric = parts[1]
            try:
                hours = float(parts[2])
            except ValueError:
                hours = 1.0
            cutoff = time.time() - hours * 3600
            with _series_lock:
                dq = _series.get(metric, deque())
                history = [(ts, v) for ts, v in dq if ts > cutoff]
            reply = json.dumps({
                "metric": metric,
                "hours": hours,
                "data": [{"ts": ts, "value": v} for ts, v in history],
                "count": len(history),
            })
        else:
            reply = json.dumps({"error": "usage: metrics_history <metric> <hours>"})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("alert_threshold "):
        parts = text.split()
        if len(parts) >= 3:
            metric = parts[1]
            try:
                value = float(parts[2])
                with _thresholds_lock:
                    _thresholds[metric] = value
                reply = f"alert threshold set: {metric} > {value}"
            except ValueError:
                reply = "invalid value — usage: alert_threshold <metric> <number>"
        else:
            reply = "usage: alert_threshold <metric> <value>"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    try:
        raw = get("/api/metrics", raw=True)
        metrics = _parse_prometheus(raw)
        for name, value in metrics.items():
            _record_metric(name, value)
        print(f"[{AGENT_ID}] recorded {len(metrics)} metrics")
    except Exception as e:
        print(f"[{AGENT_ID}] metrics fetch error: {e}")

    # Also record derived metrics from /api/status
    try:
        status = get("/api/status")
        msg_count = len(status.get("messages", []))
        task_count = len(status.get("tasks", []))
        _record_metric("status_messages_total", msg_count)
        _record_metric("status_tasks_total", task_count)
        # Track message arrival times for rate calc
        now = time.time()
        for m in status.get("messages", []):
            _message_times.append(now)
        for t in status.get("tasks", []):
            _task_times.append(now)
    except Exception as e:
        print(f"[{AGENT_ID}] status fetch error: {e}")


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
        time.sleep(60)


if __name__ == "__main__":
    main()
