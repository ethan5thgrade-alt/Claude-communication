#!/usr/bin/env python3
"""
Agent 016 — Message Archive
Role: Archives all messages to disk for audit trail.
Listens for: search_archive <query> <days>, archive_stats
Emits: archive confirmations
"""
import os
import sys
import json
import time
import glob
import requests
import threading
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_016_message_archive"
AGENT_NAME = "Agent 016 — Message Archive"
ROOM = os.environ.get("MESH_ROOM", "system")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE_DIR = os.path.join(ROOT, "archive")
_lock = threading.Lock()
_seen_msg_ids: set = set()
_total_archived = 0


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _today_archive_path() -> str:
    today = datetime.now().strftime("%Y%m%d")
    return os.path.join(ARCHIVE_DIR, f"messages_{today}.jsonl")


def _append_messages(messages: list):
    path = _today_archive_path()
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(path, "a") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")


def _search_archive(query: str, days: int = 7) -> list:
    """Search archived messages for query string within the last N days."""
    results = []
    query_lower = query.lower()
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    archive_files = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "messages_*.jsonl")), reverse=True)
    for path in archive_files:
        fname = os.path.basename(path)
        # Extract date from filename: messages_YYYYMMDD.jsonl
        try:
            file_date = fname.replace("messages_", "").replace(".jsonl", "")
            if file_date < cutoff_date:
                continue
        except Exception:
            pass

        try:
            with open(path, "r") as f:
                for line in f:
                    if query_lower in line.lower():
                        try:
                            results.append(json.loads(line.strip()))
                        except Exception:
                            results.append({"raw": line.strip()})
                        if len(results) >= 100:
                            return results
        except Exception:
            continue

    return results


def _archive_stats() -> dict:
    archive_files = glob.glob(os.path.join(ARCHIVE_DIR, "messages_*.jsonl"))
    total_size = 0
    total_lines = 0
    oldest = None
    for path in archive_files:
        try:
            size = os.path.getsize(path)
            total_size += size
            with open(path, "r") as f:
                count = sum(1 for _ in f)
            total_lines += count
            fname = os.path.basename(path)
            date_str = fname.replace("messages_", "").replace(".jsonl", "")
            if oldest is None or date_str < oldest:
                oldest = date_str
        except Exception:
            continue
    return {
        "total_files": len(archive_files),
        "total_size_bytes": total_size,
        "total_messages": total_lines,
        "oldest_date": oldest,
        "archive_dir": ARCHIVE_DIR,
    }


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("search_archive "):
        parts = text[len("search_archive "):].strip().split()
        if not parts:
            reply = json.dumps({"error": "usage: search_archive <query> [days]"})
        else:
            # Try to extract days from the end
            try:
                days = int(parts[-1])
                query = " ".join(parts[:-1])
            except ValueError:
                days = 7
                query = " ".join(parts)
            with _lock:
                results = _search_archive(query, days)
            reply = json.dumps({
                "query": query,
                "days": days,
                "results": results,
                "count": len(results),
            })
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text == "archive_stats":
        with _lock:
            stats = _archive_stats()
        reply = json.dumps(stats)
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    global _total_archived
    try:
        result = get("/api/status")
        messages = result.get("messages", [])
    except Exception as e:
        print(f"[{AGENT_ID}] error fetching status: {e}")
        return

    new_messages = []
    for msg in messages:
        msg_id = msg.get("id") or msg.get("ts") or json.dumps(msg, sort_keys=True)
        if msg_id in _seen_msg_ids:
            continue
        _seen_msg_ids.add(msg_id)
        new_messages.append(msg)

    if new_messages:
        with _lock:
            _append_messages(new_messages)
        _total_archived += len(new_messages)
        print(f"[{AGENT_ID}] archived {len(new_messages)} messages (total: {_total_archived})")

    # Prune seen IDs
    if len(_seen_msg_ids) > 20000:
        to_remove = list(_seen_msg_ids)[:10000]
        for mid in to_remove:
            _seen_msg_ids.discard(mid)


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
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
