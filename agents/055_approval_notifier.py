#!/usr/bin/env python3
"""Agent 055 — Approval Notifier
Role: Notifies pending approvers via multiple channels.
Listens for: notify_approvers <approval_id>, nudge <approval_id> <instance_id>,
             escalate_approval <approval_id>
Emits: approval notifications, nudges, escalation alerts
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_055_approval_notifier"
AGENT_NAME = "Agent 055 — Approval Notifier"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

NOTIFY_INTERVAL = 120  # seconds between auto-reminders

# ap_id -> {instance_id -> last_notified_epoch}
_notification_history = {}


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


def _notify_instance(ap_id, instance_id, action, risk):
    api("/api/send", "POST", {
        "to": instance_id,
        "from": AGENT_ID,
        "text": (
            f"[approval_notifier] ACTION NEEDED: approval '{action}' (id: {ap_id}, risk: {risk.upper()}). "
            f"Reply 'approve' or 'reject'."
        ),
        "room": ROOM,
    })
    _notification_history.setdefault(ap_id, {})[instance_id] = time.time()


def run_cycle():
    status_data = api("/api/status")
    if not isinstance(status_data, dict):
        return

    approvals = status_data.get("approvals", [])
    instances = status_data.get("instances", [])
    online_ids = {i.get("id") for i in instances if i.get("online") and i.get("id") != AGENT_ID}

    now = time.time()
    pending = [a for a in approvals if a.get("decision") is None]

    for ap in pending:
        ap_id = ap.get("id", "")
        action = ap.get("action", "?")
        risk = ap.get("risk", "low")
        voted_ids = {v.get("by", "") for v in ap.get("votes", [])}

        # Find approvers who haven't voted
        unanswered = online_ids - voted_ids

        for iid in unanswered:
            last = _notification_history.get(ap_id, {}).get(iid, 0)
            if now - last >= NOTIFY_INTERVAL:
                _notify_instance(ap_id, iid, action, risk)

    if pending:
        print(f"[{AGENT_ID}] notified approvers for {len(pending)} pending approvals")
    else:
        print(f"[{AGENT_ID}] no pending approvals")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("notify_approvers "):
        ap_id = text.split(" ", 1)[1].strip()
        status_data = api("/api/status")
        approvals = status_data.get("approvals", []) if isinstance(status_data, dict) else []
        instances = status_data.get("instances", []) if isinstance(status_data, dict) else []

        ap = next((a for a in approvals if a.get("id") == ap_id), None)
        if not ap:
            send(sender, f"approval '{ap_id}' not found")
            return

        action = ap.get("action", "?")
        risk = ap.get("risk", "?")
        online_ids = [i.get("id") for i in instances if i.get("online") and i.get("id") != AGENT_ID]
        voted_ids = {v.get("by", "") for v in ap.get("votes", [])}
        notified = []
        for iid in online_ids:
            if iid not in voted_ids:
                _notify_instance(ap_id, iid, action, risk)
                notified.append(iid)

        send(sender, f"notified {len(notified)} approvers for '{action}' (id: {ap_id}): {notified}")

    elif text.startswith("nudge "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: nudge <approval_id> <instance_id>")
            return
        ap_id, target_id = parts[1], parts[2]

        status_data = api("/api/status")
        approvals = status_data.get("approvals", []) if isinstance(status_data, dict) else []
        ap = next((a for a in approvals if a.get("id") == ap_id), None)
        if not ap:
            send(sender, f"approval '{ap_id}' not found")
            return

        _notify_instance(ap_id, target_id, ap.get("action", "?"), ap.get("risk", "?"))
        send(sender, f"nudged '{target_id}' about approval '{ap_id}'")

    elif text.startswith("escalate_approval "):
        ap_id = text.split(" ", 1)[1].strip()
        status_data = api("/api/status")
        approvals = status_data.get("approvals", []) if isinstance(status_data, dict) else []
        ap = next((a for a in approvals if a.get("id") == ap_id), None)
        if not ap:
            send(sender, f"approval '{ap_id}' not found")
            return

        action = ap.get("action", "?")
        risk = ap.get("risk", "?")
        # Escalate to all online members with urgent message
        instances_data = api(f"/api/instances?room={ROOM}")
        instances = instances_data.get("instances", []) if isinstance(instances_data, dict) else []
        for inst in instances:
            if inst.get("online") and inst.get("id") != AGENT_ID:
                api("/api/send", "POST", {
                    "to": inst.get("id"),
                    "from": AGENT_ID,
                    "text": f"[ESCALATED] Approval '{action}' (id: {ap_id}, risk: {risk.upper()}) requires URGENT decision.",
                    "room": ROOM,
                })

        broadcast(f"[approval_notifier] ESCALATED: approval '{ap_id}' for '{action}' has been escalated to all members.")
        send(sender, f"approval '{ap_id}' escalated to all online members")


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
        time.sleep(120)


if __name__ == "__main__":
    main()
