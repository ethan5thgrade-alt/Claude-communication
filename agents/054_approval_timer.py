#!/usr/bin/env python3
"""Agent 054 — Approval Timer
Role: Enforces timeouts on pending approvals.
Listens for: extend_approval <approval_id> <minutes>, approval_timeline <approval_id>
Emits: timeout reminders, auto-rejects
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_054_approval_timer"
AGENT_NAME = "Agent 054 — Approval Timer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Default timeout per risk level (seconds)
RISK_TIMEOUTS = {
    "low": 300,       # 5 min
    "medium": 900,    # 15 min
    "high": 1800,     # 30 min
    "critical": 3600, # 1 hour
}

# ap_id -> {"timeout": float (epoch), "reminded_50pct": bool, "auto_rejected": bool, "extended": int}
_timers = {}


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


def run_cycle():
    status_data = api("/api/status")
    if not isinstance(status_data, dict):
        return

    approvals = status_data.get("approvals", [])
    now = time.time()
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    for ap in approvals:
        if ap.get("decision") is not None:
            _timers.pop(ap.get("id", ""), None)
            continue

        ap_id = ap.get("id", "")
        risk = ap.get("risk", "low")
        action = ap.get("action", "?")
        requester = ap.get("requested_by", "?")
        created = ap.get("created_at", "")

        # Initialize timer if new
        if ap_id not in _timers:
            try:
                ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                timeout_sec = RISK_TIMEOUTS.get(risk, 900)
                _timers[ap_id] = {
                    "timeout": ct.timestamp() + timeout_sec,
                    "timeout_sec": timeout_sec,
                    "created_at": ct.timestamp(),
                    "reminded_50pct": False,
                    "auto_rejected": False,
                    "extended": 0,
                    "risk": risk,
                    "action": action,
                }
            except Exception:
                continue

        timer = _timers[ap_id]
        elapsed = now - timer["created_at"]
        timeout_sec = timer["timeout_sec"]
        remaining = timer["timeout"] - now

        # At 50% of timeout: send reminder
        if elapsed >= timeout_sec * 0.5 and not timer["reminded_50pct"]:
            timer["reminded_50pct"] = True
            broadcast(
                f"[approval_timer] REMINDER: approval '{action}' (id: {ap_id}) is 50% through its timeout. "
                f"{remaining/60:.0f}min remaining before auto-reject."
            )

        # At timeout: auto-reject
        if now >= timer["timeout"] and not timer["auto_rejected"]:
            timer["auto_rejected"] = True
            api("/api/approve/decide", "POST", {
                "id": ap_id,
                "decision": False,
                "by": AGENT_ID,
                "reason": "auto-rejected: timeout exceeded",
            })
            api("/api/send", "POST", {
                "to": requester,
                "from": AGENT_ID,
                "text": f"[approval_timer] Your approval request '{action}' (id: {ap_id}) was AUTO-REJECTED due to timeout.",
                "room": ROOM,
            })

    print(f"[{AGENT_ID}] monitoring {len(_timers)} approval timers")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("extend_approval "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: extend_approval <approval_id> <minutes>")
            return
        ap_id = parts[1]
        try:
            extra_min = int(parts[2])
        except ValueError:
            send(sender, "minutes must be an integer")
            return

        if ap_id in _timers:
            _timers[ap_id]["timeout"] += extra_min * 60
            _timers[ap_id]["extended"] += extra_min
            remaining = _timers[ap_id]["timeout"] - time.time()
            send(sender, f"extended approval {ap_id} by {extra_min}min. New remaining: {remaining/60:.0f}min")
        else:
            send(sender, f"approval {ap_id} not tracked (may not exist or already decided)")

    elif text.startswith("approval_timeline "):
        ap_id = text.split(" ", 1)[1].strip()
        timer = _timers.get(ap_id)
        if not timer:
            send(sender, f"no timer found for approval '{ap_id}'")
            return

        now = time.time()
        elapsed = now - timer["created_at"]
        remaining = max(0, timer["timeout"] - now)
        send(sender, json.dumps({
            "approval_id": ap_id,
            "risk": timer.get("risk", "?"),
            "action": timer.get("action", "?"),
            "elapsed_min": round(elapsed / 60, 1),
            "remaining_min": round(remaining / 60, 1),
            "timeout_min": round(timer["timeout_sec"] / 60, 1),
            "extended_min": timer.get("extended", 0),
            "reminded": timer.get("reminded_50pct", False),
            "auto_rejected": timer.get("auto_rejected", False),
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
        time.sleep(60)


if __name__ == "__main__":
    main()
