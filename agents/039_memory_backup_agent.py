#!/usr/bin/env python3
"""Agent 039 — Memory Backup Agent
Role: Backs up the memory system to disk hourly.
Listens for: backup_memory_now, restore_memory <backup_file>, memory_backup_list
Emits: backup confirmations
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_039_memory_backup_agent"
AGENT_NAME = "Agent 039 — Memory Backup Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 3600  # 1 hour
BACKUP_DIR = os.path.expanduser("~/Claude-communication/backups")
MAX_BACKUPS = 72  # 72 hourly backups = 3 days


def api(path, method="GET", data=None):
    url = f"{BROKER}{path}"
    try:
        if method == "GET":
            return requests.get(url, headers=HEADERS, timeout=5).json()
        return requests.post(url, json=data, headers=HEADERS, timeout=5).json()
    except Exception as e:
        print(f"[{AGENT_ID}] api error: {e}")
        return {}


def send(to, text):
    api("/api/send", "POST", {"to": to, "from": AGENT_ID, "text": text, "room": ROOM})


def get_memory():
    result = api("/api/memory")
    if isinstance(result, list):
        return result
    return result.get("memory", []) if isinstance(result, dict) else []


def ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def do_backup():
    ensure_backup_dir()
    entries = get_memory()
    now = datetime.datetime.now(datetime.timezone.utc)
    filename = f"memory_{now.strftime('%Y%m%d_%H')}.json"
    path = os.path.join(BACKUP_DIR, filename)

    with open(path, "w") as f:
        json.dump({
            "backup_at": now.isoformat(),
            "entry_count": len(entries),
            "memory": entries,
        }, f, indent=2, default=str)

    # Prune old backups
    prune_old_backups()
    print(f"[{AGENT_ID}] backup saved: {path} ({len(entries)} entries)")
    return path, len(entries)


def prune_old_backups():
    try:
        files = sorted([
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith("memory_") and f.endswith(".json")
        ])
        while len(files) > MAX_BACKUPS:
            oldest = os.path.join(BACKUP_DIR, files.pop(0))
            os.remove(oldest)
            print(f"[{AGENT_ID}] pruned old backup: {oldest}")
    except Exception as e:
        print(f"[{AGENT_ID}] prune error: {e}")


def run_cycle():
    try:
        path, count = do_backup()
    except Exception as e:
        print(f"[{AGENT_ID}] backup failed: {e}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "backup_memory_now":
        try:
            path, count = do_backup()
            send(sender, f"backup complete: {path} ({count} entries)")
        except Exception as e:
            send(sender, f"backup failed: {e}")

    elif text.startswith("restore_memory "):
        backup_file = text.split(" ", 1)[1].strip()
        # Resolve path
        if not os.path.isabs(backup_file):
            backup_file = os.path.join(BACKUP_DIR, backup_file)
        try:
            with open(backup_file) as f:
                data = json.load(f)
            entries = data.get("memory", [])
            restored = 0
            for entry in entries:
                api("/api/memory", "POST", {
                    "key": entry.get("key", ""),
                    "value": entry.get("value", ""),
                    "mem_type": entry.get("type", "fact"),
                })
                restored += 1
            send(sender, f"restore complete: {restored} entries from {os.path.basename(backup_file)}")
        except FileNotFoundError:
            send(sender, f"backup file not found: {backup_file}")
        except Exception as e:
            send(sender, f"restore failed: {e}")

    elif text == "memory_backup_list":
        ensure_backup_dir()
        try:
            files = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("memory_") and f.endswith(".json")])
            report = []
            for fname in files[-20:]:  # show last 20
                fpath = os.path.join(BACKUP_DIR, fname)
                try:
                    with open(fpath) as f:
                        data = json.load(f)
                    count = data.get("entry_count", len(data.get("memory", [])))
                    report.append({"file": fname, "entries": count, "backed_up_at": data.get("backup_at", "?")})
                except Exception:
                    report.append({"file": fname, "entries": "?", "backed_up_at": "?"})
            send(sender, json.dumps({"backups": report, "total": len(files)}))
        except Exception as e:
            send(sender, f"error listing backups: {e}")


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
