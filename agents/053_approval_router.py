#!/usr/bin/env python3
"""Agent 053 — Approval Router
Role: Routes approval requests to the right approvers based on risk.
Listens for: set_approver <instance_id> <risk_levels>, routing_rules
Emits: routing decisions, auto-approvals
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_053_approval_router"
AGENT_NAME = "Agent 053 — Approval Router"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

INBOX_DIR = os.path.expanduser("~/.agent-mesh-inbox")
ROUTING_FILE = os.path.join(INBOX_DIR, "approval_routing.json")

# Risk routing rules:
# low -> auto-approve after 5min with no objections
# medium -> need 1 approval
# high -> need 2 approvals
# critical -> need all online members + human bridge notification
RISK_REQUIREMENTS = {
    "low": {"required": 1, "auto_after_min": 5},
    "medium": {"required": 1, "auto_after_min": None},
    "high": {"required": 2, "auto_after_min": None},
    "critical": {"required": "all", "auto_after_min": None},
}

# Track: ap_id -> {"created_at": float, "risk": str, "auto_approved": bool}
_tracked_approvals = {}


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


def _load_routing():
    if os.path.exists(ROUTING_FILE):
        try:
            with open(ROUTING_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_routing(routing):
    os.makedirs(INBOX_DIR, exist_ok=True)
    with open(ROUTING_FILE, "w") as f:
        json.dump(routing, f, indent=2)


def run_cycle():
    status_data = api("/api/status")
    if not isinstance(status_data, dict):
        return

    approvals = status_data.get("approvals", [])
    instances = status_data.get("instances", [])
    online_count = sum(1 for i in instances if i.get("online"))
    now = time.time()
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    for ap in approvals:
        if ap.get("decision") is not None:
            continue  # already decided

        ap_id = ap.get("id", "")
        risk = ap.get("risk", "low")
        created = ap.get("created_at", "")
        votes = ap.get("votes", [])
        approve_count = sum(1 for v in votes if v.get("decision"))

        try:
            ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_min = (now_dt - ct).total_seconds() / 60
        except Exception:
            age_min = 0

        rule = RISK_REQUIREMENTS.get(risk, RISK_REQUIREMENTS["medium"])
        required = rule["required"]
        auto_min = rule.get("auto_after_min")

        # Auto-approve low risk after 5min with no objections
        if required == 1 and auto_min and age_min >= auto_min:
            reject_count = sum(1 for v in votes if not v.get("decision"))
            if reject_count == 0 and ap_id not in _tracked_approvals.get("auto_approved", set()):
                api("/api/approve/decide", "POST", {"id": ap_id, "decision": True, "by": AGENT_ID})
                broadcast(f"[approval_router] AUTO-APPROVED: {ap_id} (low risk, no objections after {auto_min}min)")
                _tracked_approvals.setdefault("auto_approved", set()).add(ap_id)

        # Check if critical needs all members
        if required == "all" and approve_count >= online_count:
            api("/api/approve/decide", "POST", {"id": ap_id, "decision": True, "by": AGENT_ID})
            broadcast(f"[approval_router] APPROVED: {ap_id} — unanimous ({approve_count}/{online_count} members)")

    print(f"[{AGENT_ID}] routed {len(approvals)} approvals, {online_count} online")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("set_approver "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: set_approver <instance_id> <risk_levels> (e.g. low,medium)")
            return
        instance_id = parts[1]
        risk_levels = [r.strip() for r in parts[2].split(",")]
        routing = _load_routing()
        routing[instance_id] = risk_levels
        _save_routing(routing)
        send(sender, f"set {instance_id} as approver for: {risk_levels}")

    elif text == "routing_rules":
        routing = _load_routing()
        lines = ["APPROVAL ROUTING RULES:", ""]
        lines.append("Risk Level Requirements:")
        for risk, rule in RISK_REQUIREMENTS.items():
            req = rule["required"]
            auto = f" (auto after {rule['auto_after_min']}min)" if rule.get("auto_after_min") else ""
            lines.append(f"  {risk:10} -> {req} approval(s){auto}")
        lines.append("")
        lines.append("Configured Approvers:")
        if routing:
            for iid, risks in routing.items():
                lines.append(f"  {iid}: {', '.join(risks)}")
        else:
            lines.append("  (none configured — all online members approve)")
        send(sender, "\n".join(lines))


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
