#!/usr/bin/env python3
"""Agent 051 — Approval Orchestrator
Role: Master coordinator for all approval workflows.
Listens for: pending_approvals, approval_stats
Emits: approval reminders, escalation notices
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_051_approval_orchestrator"
AGENT_NAME = "Agent 051 — Approval Orchestrator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

REMINDER_THRESHOLD = 300    # 5 minutes — send reminder
ESCALATION_THRESHOLD = 1800  # 30 minutes — escalate


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
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    for ap in approvals:
        if ap.get("decision") is not None:
            continue  # already decided

        created = ap.get("created_at", "")
        try:
            ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            age = (now_dt - ct).total_seconds()
        except Exception:
            continue

        ap_id = ap.get("id", "?")
        action = ap.get("action", "?")
        requester = ap.get("requested_by", "?")

        if age > ESCALATION_THRESHOLD:
            broadcast(f"[approval_orchestrator] ESCALATION: approval {ap_id} for '{action}' by {requester} pending {age/60:.0f}min — needs immediate attention")
        elif age > REMINDER_THRESHOLD:
            broadcast(f"[approval_orchestrator] REMINDER: approval {ap_id} for '{action}' pending {age/60:.0f}min — please approve/reject")

    print(f"[{AGENT_ID}] checked {len(approvals)} approvals")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "pending_approvals":
        status_data = api("/api/status")
        approvals = status_data.get("approvals", []) if isinstance(status_data, dict) else []
        pending = [a for a in approvals if a.get("decision") is None]

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        result = []
        for a in pending:
            created = a.get("created_at", "")
            age_min = 0
            try:
                ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_min = round((now_dt - ct).total_seconds() / 60, 1)
            except Exception:
                pass
            result.append({
                "id": a.get("id", "?"),
                "action": a.get("action", "?"),
                "risk": a.get("risk", "?"),
                "requested_by": a.get("requested_by", "?"),
                "age_minutes": age_min,
            })

        send(sender, json.dumps({"pending_count": len(result), "approvals": result}))

    elif text == "approval_stats":
        status_data = api("/api/status")
        approvals = status_data.get("approvals", []) if isinstance(status_data, dict) else []

        counts = {"pending": 0, "approved": 0, "rejected": 0}
        decision_times = []
        requesters = {}
        now_dt = datetime.datetime.now(datetime.timezone.utc)

        for a in approvals:
            decision = a.get("decision")
            if decision is None:
                counts["pending"] += 1
            elif decision:
                counts["approved"] += 1
            else:
                counts["rejected"] += 1

            requester = a.get("requested_by", "?")
            requesters[requester] = requesters.get(requester, 0) + 1

            if decision is not None and a.get("created_at") and a.get("decided_at"):
                try:
                    ct = datetime.datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                    dt = datetime.datetime.fromisoformat(a["decided_at"].replace("Z", "+00:00"))
                    decision_times.append((dt - ct).total_seconds())
                except Exception:
                    pass

        avg_time = round(sum(decision_times) / len(decision_times) / 60, 1) if decision_times else 0
        top_requesters = sorted(requesters.items(), key=lambda x: -x[1])[:3]

        send(sender, json.dumps({
            "counts": counts,
            "total": len(approvals),
            "avg_decision_time_min": avg_time,
            "top_requesters": top_requesters,
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
        time.sleep(30)


if __name__ == "__main__":
    main()
