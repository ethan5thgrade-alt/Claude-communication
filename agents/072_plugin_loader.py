#!/usr/bin/env python3
"""Agent 072 — Plugin Loader
Role: Loads and validates plugin manifests.
Listens for: load_plugin <name>, plugin_manifest <name>, validate_plugins
Emits: validation results, manifest data
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_072_plugin_loader"
AGENT_NAME = "Agent 072 — Plugin Loader"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

REQUIRED_FIELDS = ["name", "version"]
RECOMMENDED_FIELDS = ["description", "skills", "commands"]


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


def _fetch_plugin_manifest(name):
    """GET /api/plugins/{name} from broker."""
    url = f"{BROKER}/api/plugins/{name}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        if r.status_code == 200:
            return True, r.json()
        elif r.status_code == 404:
            return False, {"error": f"plugin '{name}' not found"}
        return False, {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return False, {"error": str(e)}


def _validate_manifest(manifest):
    """Validate a plugin manifest. Returns (valid, issues)."""
    if not isinstance(manifest, dict):
        return False, ["manifest is not a JSON object"]

    issues = []
    warnings = []

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in manifest:
            issues.append(f"missing required field: '{field}'")

    # Must have skills or commands
    has_skills = bool(manifest.get("skills"))
    has_commands = bool(manifest.get("commands"))
    if not has_skills and not has_commands:
        issues.append("must have at least one 'skills' or 'commands' entry")

    # Recommended fields
    for field in RECOMMENDED_FIELDS:
        if field not in manifest:
            warnings.append(f"missing recommended field: '{field}'")

    # Type checks
    if "version" in manifest and not isinstance(manifest["version"], str):
        issues.append("'version' must be a string")
    if "skills" in manifest and not isinstance(manifest["skills"], list):
        issues.append("'skills' must be a list")
    if "commands" in manifest and not isinstance(manifest["commands"], list):
        issues.append("'commands' must be a list")

    valid = len(issues) == 0
    return valid, {"errors": issues, "warnings": warnings}


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("load_plugin "):
        name = text[len("load_plugin "):].strip()
        ok, manifest = _fetch_plugin_manifest(name)
        if not ok:
            send(sender, json.dumps({"status": "error", "plugin": name, "error": manifest.get("error")}))
            return
        valid, result = _validate_manifest(manifest)
        send(sender, json.dumps({
            "status": "valid" if valid else "invalid",
            "plugin": name,
            "version": manifest.get("version", "unknown"),
            "validation": result,
            "has_skills": bool(manifest.get("skills")),
            "has_commands": bool(manifest.get("commands")),
            "skills_count": len(manifest.get("skills", [])),
            "commands_count": len(manifest.get("commands", [])),
        }))

    elif text.startswith("plugin_manifest "):
        name = text[len("plugin_manifest "):].strip()
        ok, manifest = _fetch_plugin_manifest(name)
        if not ok:
            send(sender, json.dumps({"error": manifest.get("error", "not found")}))
            return
        send(sender, json.dumps(manifest, indent=2, default=str))

    elif text == "validate_plugins":
        # Get all plugins from broker
        result = api("/api/plugins")
        plugins = result.get("plugins", []) if isinstance(result, dict) else []
        if not plugins:
            send(sender, "no plugins registered in broker")
            return

        summary = {"valid": [], "invalid": [], "total": len(plugins)}
        for plugin_info in plugins:
            name = plugin_info.get("name", "?")
            ok, manifest = _fetch_plugin_manifest(name)
            if not ok:
                summary["invalid"].append({"name": name, "error": "could not fetch manifest"})
                continue
            valid, validation_result = _validate_manifest(manifest)
            if valid:
                summary["valid"].append(name)
            else:
                summary["invalid"].append({
                    "name": name,
                    "errors": validation_result.get("errors", []),
                })

        send(sender, json.dumps({
            "total": summary["total"],
            "valid_count": len(summary["valid"]),
            "invalid_count": len(summary["invalid"]),
            "valid": summary["valid"],
            "invalid": summary["invalid"],
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
        time.sleep(60)


if __name__ == "__main__":
    main()
