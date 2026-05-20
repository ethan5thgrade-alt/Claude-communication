#!/usr/bin/env python3
"""Agent 076 — Skill Manager
Role: Manages Claude Code skills that can be invoked across instances.
Listens for: list_skills, invoke_skill <skill_name> <args>, skill_help <name>
Emits: skill lists, invocation requests
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_076_skill_manager"
AGENT_NAME = "Agent 076 — Skill Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

PLUGINS_CACHE_DIR = os.path.expanduser("~/.claude/plugins/cache")


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


def _scan_skills():
    """Scan ~/.claude/plugins/cache for skill files. Returns list of {name, description, path}."""
    skills = []
    if not os.path.exists(PLUGINS_CACHE_DIR):
        return skills

    for root, dirs, files in os.walk(PLUGINS_CACHE_DIR):
        for fname in files:
            fpath = os.path.join(root, fname)
            skill_entry = None

            # Handle JSON manifest files
            if fname.endswith(".json"):
                try:
                    with open(fpath) as f:
                        data = json.load(f)
                    # Could be a plugin manifest with skills
                    if isinstance(data, dict):
                        plugin_name = data.get("name", "")
                        for skill in data.get("skills", []):
                            if isinstance(skill, dict):
                                skills.append({
                                    "name": skill.get("name", ""),
                                    "description": skill.get("description", ""),
                                    "plugin": plugin_name,
                                    "path": fpath,
                                })
                            elif isinstance(skill, str):
                                skills.append({
                                    "name": skill,
                                    "description": "",
                                    "plugin": plugin_name,
                                    "path": fpath,
                                })
                except Exception:
                    pass

            # Handle Python skill files
            elif fname.endswith(".py") and not fname.startswith("_"):
                try:
                    with open(fpath) as f:
                        content = f.read(500)
                    # Extract docstring as description
                    description = ""
                    lines = content.splitlines()
                    for line in lines[1:5]:
                        stripped = line.strip().strip('"""').strip("'''").strip()
                        if stripped and not stripped.startswith("#"):
                            description = stripped
                            break
                    skills.append({
                        "name": fname[:-3],
                        "description": description,
                        "plugin": "",
                        "path": fpath,
                    })
                except Exception:
                    pass

    return skills


def _find_skill(skill_name):
    """Find a skill by name. Returns skill entry or None."""
    skills = _scan_skills()
    for s in skills:
        if s["name"].lower() == skill_name.lower():
            return s
    return None


def _find_instance_with_skill(skill_name):
    """Find an online instance that has the skill loaded (heuristic: look for agents)."""
    result = api("/api/instances")
    instances = result.get("instances", []) if isinstance(result, dict) else []
    online = [i for i in instances if i.get("online")]
    # Heuristic: return the first online instance (skills are generally available broadly)
    if online:
        return online[0].get("id")
    return None


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "list_skills":
        skills = _scan_skills()
        if not skills:
            send(sender, f"no skills found in {PLUGINS_CACHE_DIR} (directory may not exist)")
            return
        lines = []
        for s in skills:
            line = s["name"]
            if s.get("plugin"):
                line += f" [{s['plugin']}]"
            if s.get("description"):
                line += f" — {s['description']}"
            lines.append(line)
        send(sender, f"Skills ({len(lines)} total):\n" + "\n".join(f"  {l}" for l in lines))

    elif text.startswith("invoke_skill "):
        parts = text[len("invoke_skill "):].split(None, 1)
        if not parts:
            send(sender, "usage: invoke_skill <skill_name> <args>")
            return
        skill_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        skill = _find_skill(skill_name)
        if not skill:
            send(sender, f"skill '{skill_name}' not found — use 'list_skills' to see available skills")
            return
        # Find an instance to send the invocation to
        target_instance = _find_instance_with_skill(skill_name)
        if not target_instance:
            send(sender, f"no online instances found to invoke skill '{skill_name}'")
            return
        # Send invocation request to target instance
        invocation_msg = f"__skill_invoke__ {skill_name} {args}".strip()
        api("/api/send", "POST", {
            "to": target_instance,
            "from": AGENT_ID,
            "text": invocation_msg,
            "room": ROOM,
        })
        send(sender, f"skill invocation '{skill_name}' sent to instance '{target_instance}'")

    elif text.startswith("skill_help "):
        skill_name = text[len("skill_help "):].strip()
        skill = _find_skill(skill_name)
        if not skill:
            send(sender, f"skill '{skill_name}' not found")
            return
        path = skill.get("path", "")
        description = skill.get("description", "No description available.")
        # Try to read more from the file
        usage = ""
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    content = f.read(1000)
                # Extract any usage comments
                for line in content.splitlines():
                    if "usage:" in line.lower() or "args:" in line.lower():
                        usage += line.strip() + "\n"
            except Exception:
                pass
        reply = f"Skill: {skill_name}\nDescription: {description}"
        if skill.get("plugin"):
            reply += f"\nPlugin: {skill['plugin']}"
        reply += f"\nPath: {path}"
        if usage:
            reply += f"\nUsage hints:\n{usage}"
        send(sender, reply)


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
