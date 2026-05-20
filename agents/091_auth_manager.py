#!/usr/bin/env python3
"""Agent 091 — Auth Manager
Role: Manages MESH_TOKEN authentication across all connections.
"""
import os, sys, json, time, requests, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_091_auth_manager"
AGENT_NAME = "Agent 091 — Auth Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}


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


def _get_instances():
    return api("/api/instances").get("instances", [])


def run_cycle():
    """Every 300s: verify MESH_TOKEN is set, check for unauthenticated instances."""
    auth_enabled = bool(TOKEN)
    if not auth_enabled:
        print(f"[{AGENT_ID}] WARNING: MESH_TOKEN not set — auth is disabled!")
        broadcast("[SECURITY] WARNING: MESH_TOKEN not set. Authentication is disabled. "
                  "Set MESH_TOKEN to secure the mesh.")

    instances = _get_instances()
    # Instances without a registered token field (best-effort heuristic)
    suspect = [i for i in instances if not i.get("token") and not i.get("authenticated")]
    if suspect and auth_enabled:
        names = [i.get("id", "?") for i in suspect]
        print(f"[{AGENT_ID}] potentially unauthenticated instances: {names}")
        send("all", f"[AUTH ALERT] Unauthenticated instances detected: {', '.join(names)}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "auth_status":
        auth_enabled = bool(TOKEN)
        instances = _get_instances()
        authenticated = [i for i in instances if i.get("token") or i.get("authenticated")]
        unauthenticated = [i for i in instances if not i.get("token") and not i.get("authenticated")]
        lines = [
            f"Auth Status:",
            f"  Auth enabled: {auth_enabled}",
            f"  Token set:    {'yes' if auth_enabled else 'NO'}",
            f"  Total instances:         {len(instances)}",
            f"  Authenticated (approx):  {len(authenticated)}",
            f"  Unauthenticated (approx):{len(unauthenticated)}",
        ]
        send(sender, "\n".join(lines))

    elif text == "require_auth":
        api("/api/memory", "POST", {
            "key": "auth_required",
            "value": "true",
            "type": "security",
        })
        broadcast("[SECURITY] Authentication is now REQUIRED for all connections. "
                  "Set MESH_TOKEN before connecting.")
        send(sender, "Auth requirement broadcast to all instances and stored in memory.")

    elif text == "auth_report":
        data = api("/api/status")
        audit = data.get("audit", [])
        auth_events = [a for a in audit if "auth" in str(a).lower() or "token" in str(a).lower()]
        if not auth_events:
            send(sender, "No auth events found in audit log.")
        else:
            lines = [f"Auth Events ({len(auth_events)}):"]
            for e in auth_events[-20:]:
                lines.append(f"  {json.dumps(e)[:150]}")
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
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
