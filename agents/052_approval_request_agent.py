#!/usr/bin/env python3
"""Agent 052 — Approval Request Agent
Role: Creates properly formatted approval requests.
Listens for: request_approval <action> <risk_level> [approvers], bulk_approve_request <json>,
             approval_template <type>
Emits: formatted approval requests to room members
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_052_approval_request_agent"
AGENT_NAME = "Agent 052 — Approval Request Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

RISK_LEVELS = {"low", "medium", "high", "critical"}

APPROVAL_TEMPLATES = {
    "deploy": {
        "action": "Deploy to production",
        "risk": "high",
        "consequences": "Service may be temporarily interrupted. Affects all users.",
        "approve_instruction": "Reply 'approve' to proceed, 'reject' to cancel.",
    },
    "delete": {
        "action": "Delete data/resource",
        "risk": "critical",
        "consequences": "Data loss is permanent and may not be recoverable.",
        "approve_instruction": "Reply 'approve' to confirm deletion, 'reject' to cancel.",
    },
    "purchase": {
        "action": "Make a purchase/payment",
        "risk": "medium",
        "consequences": "Funds will be charged. Review amount before approving.",
        "approve_instruction": "Reply 'approve' to authorize, 'reject' to decline.",
    },
    "share": {
        "action": "Share data/access externally",
        "risk": "medium",
        "consequences": "External parties will gain access to shared information.",
        "approve_instruction": "Reply 'approve' to share, 'reject' to keep private.",
    },
}


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


def _get_online_instances():
    result = api(f"/api/instances?room={ROOM}")
    instances = result.get("instances", []) if isinstance(result, dict) else []
    return [i for i in instances if i.get("online") and i.get("id") != AGENT_ID]


def _format_request(action, risk, consequences="", requester=""):
    risk_emoji = {"low": "[LOW]", "medium": "[MED]", "high": "[HIGH]", "critical": "[CRIT]"}.get(risk, "[?]")
    lines = [
        f"=== APPROVAL REQUEST {risk_emoji} ===",
        f"Action:       {action}",
        f"Risk Level:   {risk.upper()}",
        f"Requested by: {requester}",
    ]
    if consequences:
        lines.append(f"Consequences: {consequences}")
    lines.append("To approve: send 'approve <id>' | To reject: send 'reject <id>'")
    return "\n".join(lines)


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("request_approval "):
        rest = text[len("request_approval "):].strip()
        parts = rest.split()
        if len(parts) < 2:
            send(sender, "usage: request_approval <action> <risk_level> [approvers...]")
            return
        action = parts[0]
        risk = parts[1].lower()
        if risk not in RISK_LEVELS:
            send(sender, f"invalid risk level '{risk}'. Valid: {sorted(RISK_LEVELS)}")
            return

        approvers = parts[2:] if len(parts) > 2 else None

        # POST approval request to broker
        result = api("/api/approve", "POST", {
            "action": action,
            "risk": risk,
            "requested_by": sender,
            "room": ROOM,
        })
        ap_id = result.get("id", "pending")

        formatted = _format_request(action, risk, requester=sender)
        if approvers:
            for approver in approvers:
                api("/api/send", "POST", {
                    "to": approver,
                    "from": AGENT_ID,
                    "text": formatted,
                    "room": ROOM,
                })
        else:
            # Send to all online instances
            online = _get_online_instances()
            for inst in online:
                api("/api/send", "POST", {
                    "to": inst.get("id"),
                    "from": AGENT_ID,
                    "text": formatted,
                    "room": ROOM,
                })

        send(sender, f"approval request submitted (id: {ap_id}). Notified approvers.")

    elif text.startswith("bulk_approve_request "):
        json_str = text[len("bulk_approve_request "):].strip()
        try:
            actions = json.loads(json_str)
            if not isinstance(actions, list):
                raise ValueError("expected JSON array")
        except Exception as e:
            send(sender, f"invalid JSON: {e}")
            return

        ids = []
        for item in actions:
            action = item.get("action", "")
            risk = item.get("risk", "low")
            result = api("/api/approve", "POST", {
                "action": action,
                "risk": risk,
                "requested_by": sender,
                "room": ROOM,
            })
            ids.append(result.get("id", "?"))

        formatted = "\n".join([
            f"BULK APPROVAL REQUEST ({len(actions)} actions):",
            "\n".join(f"  {i+1}. [{a.get('risk','?').upper()}] {a.get('action','?')}"
                      for i, a in enumerate(actions)),
            "Reply 'approve all' or 'reject all' or address individual IDs.",
        ])
        broadcast(formatted)
        send(sender, f"bulk request submitted: {len(ids)} approvals created")

    elif text.startswith("approval_template "):
        tmpl_type = text.split(" ", 1)[1].strip()
        tmpl = APPROVAL_TEMPLATES.get(tmpl_type)
        if tmpl:
            send(sender, json.dumps({
                "template_type": tmpl_type,
                **tmpl,
                "usage": f"request_approval \"{tmpl['action']}\" {tmpl['risk']}",
            }))
        else:
            send(sender, f"unknown template '{tmpl_type}'. Available: {list(APPROVAL_TEMPLATES.keys())}")


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
            time.sleep(30)
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")


if __name__ == "__main__":
    main()
