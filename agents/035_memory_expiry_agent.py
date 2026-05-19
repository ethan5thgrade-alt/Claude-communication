#!/usr/bin/env python3
"""Agent 035 — Memory Expiry Agent
Role: Removes expired and stale memory entries (dry-run, logs locally).
Listens for: expire_now <key>, expiry_report
Emits: expiry logs
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_035_memory_expiry_agent"
AGENT_NAME = "Agent 035 — Memory Expiry Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 3600  # 1 hour
EXPIRY_LOG_PATH = os.path.expanduser("~/Claude-communication/expiry_log.json")
SESSION_TTL_HOURS = 24


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


def load_expiry_log():
    try:
        with open(EXPIRY_LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"expired": []}


def save_expiry_log(log):
    try:
        with open(EXPIRY_LOG_PATH, "w") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"[{AGENT_ID}] failed to save expiry log: {e}")


def check_expired(entries):
    """Return list of (key, reason) for entries that should be expired."""
    expired = []
    now = datetime.datetime.now(datetime.timezone.utc)

    for entry in entries:
        key = entry.get("key", "")
        value = str(entry.get("value", ""))
        ts_str = entry.get("ts") or entry.get("created_at") or ""

        # tmp: prefix older than 24h
        if key.startswith("tmp:") and ts_str:
            try:
                ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_hours = (now - ts).total_seconds() / 3600
                if age_hours > SESSION_TTL_HOURS:
                    expired.append((key, f"tmp: prefix, age={age_hours:.1f}h"))
                    continue
            except Exception:
                pass

        # Check for "expires:<date>" pattern in value
        if "expires:" in value:
            import re
            m = re.search(r'expires:(\S+)', value)
            if m:
                try:
                    exp_date = datetime.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                    if now > exp_date:
                        expired.append((key, f"explicit expiry {m.group(1)}"))
                except Exception:
                    pass

    return expired


def run_cycle():
    entries = get_memory()
    expired = check_expired(entries)

    if expired:
        log = load_expiry_log()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for key, reason in expired:
            log["expired"].append({"key": key, "reason": reason, "logged_at": now_str})
        save_expiry_log(log)
        print(f"[{AGENT_ID}] logged {len(expired)} expired entries (dry run — broker has no delete)")
    else:
        print(f"[{AGENT_ID}] no expired entries found")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("expire_now "):
        key = text.split(" ", 1)[1].strip()
        log = load_expiry_log()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log["expired"].append({"key": key, "reason": "manual expire_now", "logged_at": now_str})
        save_expiry_log(log)
        send(sender, f"key '{key}' marked as expired in local log")

    elif text == "expiry_report":
        log = load_expiry_log()
        expired_list = log.get("expired", [])
        # Show last 20
        recent = expired_list[-20:]
        send(sender, json.dumps({
            "total_expired_logged": len(expired_list),
            "recent": recent,
            "note": "broker has no delete endpoint; entries tracked locally only",
        }))


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
