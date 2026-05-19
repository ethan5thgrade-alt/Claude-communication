#!/usr/bin/env python3
"""Agent 088 — Instance Specializer
Role: Assigns specialized roles to Claude instances (researcher, builder, reviewer, tester, etc.)
"""
import os, sys, json, time, requests, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_088_instance_specializer"
AGENT_NAME = "Agent 088 — Instance Specializer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

VALID_ROLES = {"researcher", "architect", "builder", "reviewer", "tester", "deployer", "documenter"}

# instance_id -> role
_role_assignments = {}


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


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("specialize "):
        # specialize <instance_id> <role>
        parts = text[len("specialize "):].strip().split()
        if len(parts) < 2:
            send(sender, "Usage: specialize <instance_id> <role>")
            return
        inst_id, role = parts[0], parts[1].lower()
        if role not in VALID_ROLES:
            send(sender, f"Invalid role '{role}'. Valid: {', '.join(sorted(VALID_ROLES))}")
            return
        _role_assignments[inst_id] = role
        # Write to memory
        api("/api/memory", "POST", {
            "key": f"role_{inst_id}",
            "value": role,
            "type": "specialization",
        })
        # Notify instance
        send(inst_id, f"[ROLE ASSIGNED] You are now the '{role}' specialist. "
                      f"Focus your work on {role}-related tasks.")
        broadcast(f"[SPECIALIZATION] {inst_id} assigned role: {role}")
        send(sender, f"Instance '{inst_id}' specialized as '{role}'.")

    elif text.startswith("find_specialist "):
        role = text[len("find_specialist "):].strip().lower()
        matches = [iid for iid, r in _role_assignments.items() if r == role]
        if not matches:
            # Check memory as fallback
            memories = api("/api/memory").get("memory", [])
            for m in memories:
                if m.get("type") == "specialization" and m.get("value") == role:
                    key = m.get("key", "")
                    if key.startswith("role_"):
                        iid = key[len("role_"):]
                        matches.append(iid)
        if matches:
            send(sender, f"Specialist for '{role}': {', '.join(matches)}")
        else:
            send(sender, f"No specialist found for role '{role}'.")

    elif text == "role_assignments":
        if not _role_assignments:
            # Try loading from memory
            memories = api("/api/memory").get("memory", [])
            for m in memories:
                if m.get("type") == "specialization" and m.get("key", "").startswith("role_"):
                    iid = m.get("key")[len("role_"):]
                    _role_assignments[iid] = m.get("value", "")
        if not _role_assignments:
            send(sender, "No role assignments recorded.")
            return
        lines = ["Current Role Assignments:"]
        for iid, role in sorted(_role_assignments.items()):
            lines.append(f"  {iid}: {role}")
        send(sender, "\n".join(lines))

    elif text == "rotate_roles":
        instances = _get_instances()
        online = [i.get("id") for i in instances if i.get("online") and i.get("id") != AGENT_ID]
        if not online:
            send(sender, "No online instances to rotate roles.")
            return
        roles = list(VALID_ROLES)
        random.shuffle(roles)
        new_assignments = {}
        for idx, iid in enumerate(online):
            role = roles[idx % len(roles)]
            new_assignments[iid] = role
            _role_assignments[iid] = role
            api("/api/memory", "POST", {
                "key": f"role_{iid}",
                "value": role,
                "type": "specialization",
            })
            send(iid, f"[ROLE ROTATION] Your new role: '{role}'.")
        lines = ["Roles rotated:"]
        for iid, role in new_assignments.items():
            lines.append(f"  {iid}: {role}")
        broadcast("\n".join(lines))
        send(sender, f"Rotated roles for {len(new_assignments)} instances.")


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
            pass  # no periodic cycle
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
