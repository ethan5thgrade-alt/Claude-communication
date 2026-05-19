#!/usr/bin/env python3
"""Agent 094 — Intrusion Detector
Role: Detects unauthorized access attempts and suspicious patterns.
"""
import os, sys, json, time, requests, datetime, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_094_intrusion_detector"
AGENT_NAME = "Agent 094 — Intrusion Detector"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

_blocklist = set()
_suspicious_events = []  # list of {ts, type, detail}
_message_counts = {}  # sender -> [ts, ts, ...]  for burst detection

INJECTION_PATTERNS = [
    r";\s*drop\s+table",
    r"<script",
    r"\$\{jndi:",
    r"\.\.\/",
    r"exec\s*\(",
    r"os\.system",
    r"__import__",
]


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


def _flag_event(event_type, detail):
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _suspicious_events.append({"ts": ts, "type": event_type, "detail": detail})
    print(f"[{AGENT_ID}] SUSPICIOUS: {event_type} — {detail}")


def _check_injection(text):
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def run_cycle():
    """Every 30s: scan recent messages for suspicious patterns."""
    data = api("/api/status")
    messages = data.get("messages", [])[-100:]
    instances = api("/api/instances").get("instances", [])
    known_ids = {i.get("id") for i in instances}

    now = datetime.datetime.now(datetime.timezone.utc)
    one_min_ago = now - datetime.timedelta(minutes=1)

    for m in messages:
        sender = m.get("from", "")
        text = m.get("text", "")

        if not sender:
            continue

        # Check blocklist
        if sender in _blocklist:
            continue  # already flagged

        # Unknown instance ID
        if sender not in known_ids and sender not in ("all", AGENT_ID):
            _flag_event("unknown_instance", f"Message from unregistered instance: {sender}")

        # Injection pattern detection
        if _check_injection(text):
            _flag_event("injection_attempt", f"Injection pattern in message from {sender}: {text[:100]}")
            broadcast(f"[INTRUSION ALERT] Injection pattern detected from {sender}!")

        # Burst detection: >20 messages per minute from same sender
        ts_str = m.get("ts", "")
        try:
            ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            _message_counts.setdefault(sender, [])
            _message_counts[sender].append(ts)
            # Prune old
            _message_counts[sender] = [t for t in _message_counts[sender] if t > one_min_ago]
            if len(_message_counts[sender]) > 20:
                _flag_event("message_burst", f"Burst detected from {sender}: "
                             f"{len(_message_counts[sender])} msgs/min")
        except Exception:
            pass

    # Prune old events (keep last 1000)
    if len(_suspicious_events) > 1000:
        _suspicious_events[:] = _suspicious_events[-1000:]


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "intrusion_report":
        now = datetime.datetime.now(datetime.timezone.utc)
        one_hr_ago = now - datetime.timedelta(hours=1)
        recent = [e for e in _suspicious_events
                  if datetime.datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) > one_hr_ago]
        if not recent:
            send(sender, "No suspicious events in the last hour.")
        else:
            lines = [f"Suspicious Events (last hr): {len(recent)}"]
            for e in recent[-20:]:
                lines.append(f"  [{e['ts'][:19]}] {e['type']}: {e['detail'][:100]}")
            send(sender, "\n".join(lines))

    elif text.startswith("block_instance "):
        inst_id = text[len("block_instance "):].strip()
        _blocklist.add(inst_id)
        broadcast(f"[SECURITY] Instance '{inst_id}' added to blocklist by {sender}.")
        send(sender, f"Instance '{inst_id}' blocked.")

    elif text == "threat_level":
        now = datetime.datetime.now(datetime.timezone.utc)
        one_hr_ago = now - datetime.timedelta(hours=1)
        recent = [e for e in _suspicious_events
                  if datetime.datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) > one_hr_ago]
        count = len(recent)
        if count == 0:
            level = "green"
        elif count < 5:
            level = "yellow"
        else:
            level = "red"
        send(sender, f"Threat Level: {level.upper()} ({count} suspicious event(s) in last hr)")

    elif text == "security_scan":
        run_cycle()
        now = datetime.datetime.now(datetime.timezone.utc)
        one_hr_ago = now - datetime.timedelta(hours=1)
        recent = [e for e in _suspicious_events
                  if datetime.datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) > one_hr_ago]
        send(sender, f"Security scan complete. {len(recent)} suspicious event(s) found in last hr. "
                     f"Blocklist: {len(_blocklist)} instance(s).")


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
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
