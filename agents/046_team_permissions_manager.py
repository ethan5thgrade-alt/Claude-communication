#!/usr/bin/env python3
"""Agent 046 — Team Permissions Manager
Role: Manages what each team member can do (read/write/admin).
Listens for: grant <instance_id> <permission>, revoke <instance_id> <permission>,
             check_permission <instance_id> <permission>, permissions_list
Emits: grant/revoke confirmations, permission check results
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_046_team_permissions_manager"
AGENT_NAME = "Agent 046 — Team Permissions Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

INBOX_DIR = os.path.expanduser("~/.agent-mesh-inbox")
PERMISSIONS_FILE = os.path.join(INBOX_DIR, "permissions.json")

VALID_PERMISSIONS = {"read", "write", "admin", "create_tasks", "approve"}


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


def _load_permissions():
    if os.path.exists(PERMISSIONS_FILE):
        try:
            with open(PERMISSIONS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_permissions(perms):
    os.makedirs(INBOX_DIR, exist_ok=True)
    with open(PERMISSIONS_FILE, "w") as f:
        json.dump(perms, f, indent=2)


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("grant "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: grant <instance_id> <permission>")
            return
        instance_id, permission = parts[1], parts[2]
        if permission not in VALID_PERMISSIONS:
            send(sender, f"invalid permission '{permission}'. Valid: {sorted(VALID_PERMISSIONS)}")
            return
        perms = _load_permissions()
        if instance_id not in perms:
            perms[instance_id] = []
        if permission not in perms[instance_id]:
            perms[instance_id].append(permission)
        _save_permissions(perms)
        send(sender, f"granted '{permission}' to '{instance_id}'")

    elif text.startswith("revoke "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: revoke <instance_id> <permission>")
            return
        instance_id, permission = parts[1], parts[2]
        perms = _load_permissions()
        if instance_id in perms and permission in perms[instance_id]:
            perms[instance_id].remove(permission)
            if not perms[instance_id]:
                del perms[instance_id]
            _save_permissions(perms)
            send(sender, f"revoked '{permission}' from '{instance_id}'")
        else:
            send(sender, f"'{instance_id}' did not have permission '{permission}'")

    elif text.startswith("check_permission "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: check_permission <instance_id> <permission>")
            return
        instance_id, permission = parts[1], parts[2]
        perms = _load_permissions()
        instance_perms = perms.get(instance_id, [])
        has_perm = permission in instance_perms or "admin" in instance_perms
        send(sender, json.dumps({
            "instance_id": instance_id,
            "permission": permission,
            "granted": has_perm,
            "all_permissions": instance_perms,
        }))

    elif text == "permissions_list":
        perms = _load_permissions()
        if not perms:
            send(sender, "no permissions configured")
            return
        lines = ["INSTANCE                           PERMISSIONS"]
        lines.append("-" * 55)
        for iid, plist in sorted(perms.items()):
            lines.append(f"{iid:<35} {', '.join(sorted(plist))}")
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
            time.sleep(30)
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")


if __name__ == "__main__":
    main()
