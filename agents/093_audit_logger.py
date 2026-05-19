#!/usr/bin/env python3
"""Agent 093 — Audit Logger
Role: Maintains a comprehensive, tamper-evident audit trail with SHA-256 hash chaining.
"""
import os, sys, json, time, requests, datetime, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_093_audit_logger"
AGENT_NAME = "Agent 093 — Audit Logger"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

AUDIT_PATH = os.path.expanduser("~/Claude-communication/logs/audit_chain.jsonl")

_last_hash = "0" * 64  # genesis hash
_seen_entry_ids = set()


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


def broadcast(text):
    send("all", text)


def _ensure_log_dir():
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)


def _load_last_hash():
    global _last_hash
    _ensure_log_dir()
    try:
        with open(AUDIT_PATH) as f:
            lines = f.readlines()
        if lines:
            last = json.loads(lines[-1])
            _last_hash = last.get("chain_hash", "0" * 64)
    except (FileNotFoundError, json.JSONDecodeError):
        _last_hash = "0" * 64


def _append_entry(entry_data):
    global _last_hash
    entry_str = json.dumps(entry_data, sort_keys=True)
    chain_hash = hashlib.sha256((_last_hash + entry_str).encode()).hexdigest()
    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "data": entry_data,
        "prev_hash": _last_hash,
        "chain_hash": chain_hash,
    }
    with open(AUDIT_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
    _last_hash = chain_hash


def run_cycle():
    """Every 60s: pull audit array from broker status, hash-chain new entries."""
    _load_last_hash()
    data = api("/api/status")
    audit_entries = data.get("audit", [])
    new_count = 0
    for entry in audit_entries:
        entry_id = entry.get("id") or json.dumps(entry, sort_keys=True)[:50]
        if entry_id not in _seen_entry_ids:
            _seen_entry_ids.add(entry_id)
            _append_entry(entry)
            new_count += 1
    if new_count:
        print(f"[{AGENT_ID}] chained {new_count} new audit entries")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("audit_tail "):
        n_str = text[len("audit_tail "):].strip()
        try:
            n = int(n_str)
        except ValueError:
            n = 10
        try:
            with open(AUDIT_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            send(sender, "Audit log is empty.")
            return
        tail = lines[-n:]
        result_lines = [f"Last {len(tail)} audit entries:"]
        for line in tail:
            try:
                r = json.loads(line)
                result_lines.append(f"  [{r.get('ts', '')[:19]}] {json.dumps(r.get('data', ''))[:120]} "
                                     f"hash={r.get('chain_hash', '')[:12]}...")
            except Exception:
                result_lines.append(f"  {line[:150]}")
        send(sender, "\n".join(result_lines))

    elif text == "audit_verify":
        try:
            with open(AUDIT_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            send(sender, "Audit log is empty — nothing to verify.")
            return
        prev_hash = "0" * 64
        errors = 0
        for i, line in enumerate(lines):
            try:
                r = json.loads(line)
                entry_str = json.dumps(r.get("data", {}), sort_keys=True)
                expected = hashlib.sha256((prev_hash + entry_str).encode()).hexdigest()
                if r.get("chain_hash") != expected:
                    errors += 1
                prev_hash = r.get("chain_hash", prev_hash)
            except Exception as e:
                errors += 1
        if errors == 0:
            send(sender, f"Audit chain VERIFIED — {len(lines)} entries, all hashes valid.")
        else:
            send(sender, f"Audit chain TAMPERED — {errors} hash mismatches found in {len(lines)} entries!")

    elif text.startswith("audit_search "):
        query = text[len("audit_search "):].strip().lower()
        try:
            with open(AUDIT_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            send(sender, "Audit log is empty.")
            return
        matches = []
        for line in lines:
            if query in line.lower():
                matches.append(line.strip()[:200])
        if not matches:
            send(sender, f"No audit entries matching '{query}'.")
        else:
            send(sender, f"Found {len(matches)} match(es) for '{query}':\n" +
                 "\n".join(f"  {m}" for m in matches[-10:]))

    elif text.startswith("audit_export "):
        # audit_export <from_date> <to_date> e.g. 2025-01-01 2025-12-31
        parts = text[len("audit_export "):].strip().split()
        if len(parts) < 2:
            send(sender, "Usage: audit_export <from_date> <to_date> (YYYY-MM-DD)")
            return
        from_date, to_date = parts[0], parts[1]
        try:
            with open(AUDIT_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            send(sender, "Audit log is empty.")
            return
        filtered = []
        for line in lines:
            try:
                r = json.loads(line)
                ts = r.get("ts", "")[:10]
                if from_date <= ts <= to_date:
                    filtered.append(r)
            except Exception:
                pass
        send(sender, f"Exported {len(filtered)} entries from {from_date} to {to_date}:\n" +
             json.dumps(filtered[:50], indent=2)[:2000])


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _load_last_hash()
    _connect_mod.start()
    _connect_mod.on_message(handle_message)
    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
