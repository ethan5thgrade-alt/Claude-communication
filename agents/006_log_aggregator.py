#!/usr/bin/env python3
"""
Agent 006 — Log Aggregator
Role: Collects all agent logs into a unified structured log.
Listens for: get_logs <n>, search_logs <query>, log_stats
Emits: log entries to daily JSONL files
"""
import os
import sys
import json
import time
import glob
import requests
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_006_log_aggregator"
AGENT_NAME = "Agent 006 — Log Aggregator"
ROOM = os.environ.get("MESH_ROOM", "system")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(ROOT, "logs")
_lock = threading.Lock()
_seen_audit_ids: set = set()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _today_log_path() -> str:
    today = datetime.now().strftime("%Y%m%d")
    return os.path.join(LOGS_DIR, f"audit_{today}.jsonl")


def _append_log_entries(entries: list):
    path = _today_log_path()
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(path, "a") as f:
        for entry in entries:
            f.write(json.dumps(entry, default=str) + "\n")


def _read_log_lines(n: int) -> list:
    """Read last N lines from recent log files."""
    logs = sorted(glob.glob(os.path.join(LOGS_DIR, "audit_*.jsonl")), reverse=True)
    lines = []
    for log_path in logs:
        try:
            with open(log_path, "r") as f:
                file_lines = f.readlines()
            lines = file_lines + lines
            if len(lines) >= n:
                break
        except Exception:
            continue
    parsed = []
    for line in lines[-n:]:
        try:
            parsed.append(json.loads(line.strip()))
        except Exception:
            parsed.append({"raw": line.strip()})
    return parsed


def _search_logs(query: str, max_results: int = 50) -> list:
    """Search all log files for query string."""
    logs = sorted(glob.glob(os.path.join(LOGS_DIR, "audit_*.jsonl")), reverse=True)
    matches = []
    query_lower = query.lower()
    for log_path in logs:
        try:
            with open(log_path, "r") as f:
                for line in f:
                    if query_lower in line.lower():
                        try:
                            matches.append(json.loads(line.strip()))
                        except Exception:
                            matches.append({"raw": line.strip()})
                        if len(matches) >= max_results:
                            return matches
        except Exception:
            continue
    return matches


def _compute_log_stats() -> dict:
    """Compute message count by hour, by agent, error rate."""
    logs = sorted(glob.glob(os.path.join(LOGS_DIR, "audit_*.jsonl")), reverse=True)[:3]
    by_hour: dict = {}
    by_agent: dict = {}
    error_count = 0
    total = 0
    for log_path in logs:
        try:
            with open(log_path, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        total += 1
                        ts = entry.get("ts", "")
                        hour = ts[11:13] if len(ts) >= 13 else "??"
                        by_hour[hour] = by_hour.get(hour, 0) + 1
                        agent = entry.get("by") or entry.get("from") or entry.get("instance_id") or "unknown"
                        by_agent[agent] = by_agent.get(agent, 0) + 1
                        level = entry.get("level", "")
                        if level in ("error", "warn"):
                            error_count += 1
                    except Exception:
                        continue
        except Exception:
            continue
    return {
        "total_entries": total,
        "by_hour": by_hour,
        "by_agent": by_agent,
        "error_count": error_count,
        "error_rate": round(error_count / total, 4) if total > 0 else 0,
    }


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("get_logs "):
        try:
            n = int(text[len("get_logs "):].strip())
        except ValueError:
            n = 20
        with _lock:
            entries = _read_log_lines(n)
        reply = json.dumps({"entries": entries, "count": len(entries)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("search_logs "):
        query = text[len("search_logs "):].strip()
        with _lock:
            matches = _search_logs(query)
        reply = json.dumps({"query": query, "matches": matches, "count": len(matches)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "log_stats":
        with _lock:
            stats = _compute_log_stats()
        reply = json.dumps(stats)
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    """Fetch /api/status audit entries and append new ones to today's log."""
    try:
        result = get("/api/status")
    except Exception as e:
        print(f"[{AGENT_ID}] error fetching status: {e}")
        return

    audit = result.get("audit", [])
    new_entries = []
    with _lock:
        for entry in audit:
            eid = entry.get("id") or entry.get("ts") or str(entry)
            if eid not in _seen_audit_ids:
                _seen_audit_ids.add(eid)
                new_entries.append(entry)

    if new_entries:
        with _lock:
            _append_log_entries(new_entries)
        print(f"[{AGENT_ID}] appended {len(new_entries)} new audit entries")


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    os.makedirs(LOGS_DIR, exist_ok=True)
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
