#!/usr/bin/env python3
"""Agent 075 — Plugin Updater
Role: Checks for plugin updates and applies them.
Listens for: check_updates, plugin_changelog <name>, update_plugin <name>
Emits: update availability alerts
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_075_plugin_updater"
AGENT_NAME = "Agent 075 — Plugin Updater"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

VERSIONS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugin_versions.json"
)

# Known latest versions: {plugin_name: {latest_version, changelog, checked_at}}
_known_versions = {}
_last_cycle_ts = 0


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


def _load_versions():
    global _known_versions
    if not os.path.exists(VERSIONS_FILE):
        return
    try:
        with open(VERSIONS_FILE) as f:
            _known_versions = json.load(f)
    except Exception:
        pass


def _save_versions():
    try:
        with open(VERSIONS_FILE, "w") as f:
            json.dump(_known_versions, f, indent=2, default=str)
    except Exception as e:
        print(f"[{AGENT_ID}] save error: {e}")


def _version_tuple(ver_str):
    """Parse a version string into comparable tuple."""
    try:
        parts = str(ver_str).strip("v").split(".")
        return tuple(int(p) for p in parts if p.isdigit())
    except Exception:
        return (0,)


def _is_newer(current, known_latest):
    """Return True if known_latest is newer than current."""
    return _version_tuple(known_latest) > _version_tuple(current)


def run_cycle():
    global _last_cycle_ts
    result = api("/api/plugins")
    plugins = result.get("plugins", []) if isinstance(result, dict) else []

    outdated = []
    for plugin in plugins:
        name = plugin.get("name", "")
        current_ver = str(plugin.get("version", "0.0.0"))
        if not name:
            continue

        # Update our version record with the currently installed version
        if name not in _known_versions:
            _known_versions[name] = {
                "installed_version": current_ver,
                "latest_version": current_ver,
                "changelog": "",
                "checked_at": time.time(),
            }
        else:
            # Check if broker has a newer version in the marketplace field
            marketplace_version = plugin.get("marketplace_version") or plugin.get("latest_version")
            if marketplace_version and _is_newer(current_ver, marketplace_version):
                _known_versions[name]["latest_version"] = marketplace_version
                outdated.append({
                    "name": name,
                    "installed": current_ver,
                    "latest": marketplace_version,
                })
            _known_versions[name]["installed_version"] = current_ver
            _known_versions[name]["checked_at"] = time.time()

    _save_versions()
    _last_cycle_ts = time.time()

    if outdated:
        names = [p["name"] for p in outdated]
        broadcast(f"[plugin_updater] {len(outdated)} plugin(s) have updates available: {', '.join(names)}")

    print(f"[{AGENT_ID}] checked {len(plugins)} plugins, {len(outdated)} updates available")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "check_updates":
        result = api("/api/plugins")
        plugins = result.get("plugins", []) if isinstance(result, dict) else []
        outdated = []
        uptodate = []
        for plugin in plugins:
            name = plugin.get("name", "")
            current_ver = str(plugin.get("version", "0.0.0"))
            known = _known_versions.get(name, {})
            latest = known.get("latest_version", current_ver)
            if _is_newer(current_ver, latest):
                outdated.append({"name": name, "installed": current_ver, "latest": latest})
            else:
                uptodate.append(name)
        send(sender, json.dumps({
            "total_plugins": len(plugins),
            "updates_available": len(outdated),
            "outdated": outdated,
            "uptodate": uptodate,
            "last_checked": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(_last_cycle_ts)
            ) if _last_cycle_ts else "never",
        }))

    elif text.startswith("plugin_changelog "):
        name = text[len("plugin_changelog "):].strip()
        known = _known_versions.get(name)
        if not known:
            send(sender, f"no version info for plugin '{name}' — not found or not yet scanned")
            return
        changelog = known.get("changelog", "")
        latest = known.get("latest_version", "unknown")
        installed = known.get("installed_version", "unknown")
        if changelog:
            send(sender, f"Plugin '{name}' changelog (installed: {installed}, latest: {latest}):\n{changelog}")
        else:
            send(sender, (
                f"Plugin '{name}': installed={installed}, latest={latest}\n"
                "No changelog available. Check the plugin's marketplace page for details."
            ))

    elif text.startswith("update_plugin "):
        name = text[len("update_plugin "):].strip()
        known = _known_versions.get(name, {})
        installed = known.get("installed_version", "unknown")
        latest = known.get("latest_version", installed)
        if installed == latest:
            send(sender, f"Plugin '{name}' is already at the latest version ({installed})")
            return
        # Output instructions — actual update must be done by user
        reply = (
            f"Update instructions for plugin '{name}':\n"
            f"  Installed: {installed}\n"
            f"  Latest:    {latest}\n\n"
            f"To update, run one of:\n"
            f"  claude install {name}  (if using Claude Code marketplace)\n"
            f"  pip install --upgrade {name}  (if pip-installable)\n"
            f"  Or check the plugin's documentation for update steps.\n\n"
            f"After updating, restart the broker to load the new version."
        )
        send(sender, reply)


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _load_versions()
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(3600)


if __name__ == "__main__":
    main()
