#!/usr/bin/env python3
"""Agent 071 — Plugin Registry
Role: Tracks all installed Claude Code plugins and makes them discoverable.
Listens for: list_plugins, plugin_info <name>, find_plugin <capability>
Emits: plugin lists, plugin info
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_071_plugin_registry"
AGENT_NAME = "Agent 071 — Plugin Registry"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

PLUGIN_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugin_cache.json"
)

# Local plugin cache: {name: {name, version, marketplace, description, skills, ...}}
_plugin_cache = {}
_last_scan_ts = 0
_last_plugin_names = set()


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


def _save_cache():
    try:
        with open(PLUGIN_CACHE_FILE, "w") as f:
            json.dump({
                "last_scan": _last_scan_ts,
                "plugins": _plugin_cache,
            }, f, indent=2, default=str)
    except Exception as e:
        print(f"[{AGENT_ID}] cache save error: {e}")


def _load_cache():
    global _plugin_cache, _last_scan_ts
    if not os.path.exists(PLUGIN_CACHE_FILE):
        return
    try:
        with open(PLUGIN_CACHE_FILE) as f:
            data = json.load(f)
        _plugin_cache = data.get("plugins", {})
        _last_scan_ts = data.get("last_scan", 0)
    except Exception:
        pass


def _format_plugin(name, info):
    """Format a plugin entry for display."""
    version = info.get("version", "unknown")
    marketplace = info.get("marketplace", "")
    description = info.get("description", "")
    skills = info.get("skills", [])
    return (
        f"{name} v{version}"
        + (f" [{marketplace}]" if marketplace else "")
        + (f" — {description}" if description else "")
        + (f" | skills: {', '.join(skills)}" if skills else "")
    )


def run_cycle():
    global _plugin_cache, _last_scan_ts, _last_plugin_names
    result = api("/api/plugins")
    plugins = result.get("plugins", []) if isinstance(result, dict) else []

    new_cache = {}
    for p in plugins:
        name = p.get("name", "")
        if name:
            new_cache[name] = p

    # Detect new plugins
    current_names = set(new_cache.keys())
    new_plugins = current_names - _last_plugin_names
    if new_plugins and _last_plugin_names:
        broadcast(f"[plugin_registry] new plugins detected: {', '.join(new_plugins)}")

    _plugin_cache = new_cache
    _last_plugin_names = current_names
    _last_scan_ts = time.time()
    _save_cache()
    print(f"[{AGENT_ID}] scanned {len(_plugin_cache)} plugins")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "list_plugins":
        if not _plugin_cache:
            send(sender, "no plugins in registry — waiting for next scan cycle")
            return
        lines = []
        for name, info in sorted(_plugin_cache.items()):
            lines.append(_format_plugin(name, info))
        reply = f"Plugins ({len(lines)} total):\n" + "\n".join(f"  {l}" for l in lines)
        send(sender, reply)

    elif text.startswith("plugin_info "):
        name = text[len("plugin_info "):].strip()
        info = _plugin_cache.get(name)
        if not info:
            # Try case-insensitive search
            for k, v in _plugin_cache.items():
                if k.lower() == name.lower():
                    info = v
                    name = k
                    break
        if not info:
            send(sender, f"plugin '{name}' not found in registry")
            return
        send(sender, json.dumps(info, indent=2, default=str))

    elif text.startswith("find_plugin "):
        capability = text[len("find_plugin "):].strip().lower()
        matches = []
        for name, info in _plugin_cache.items():
            # Search name, description, skills
            searchable = " ".join([
                name,
                info.get("description", ""),
                info.get("marketplace", ""),
                " ".join(info.get("skills", [])),
                " ".join(info.get("commands", [])),
            ]).lower()
            if capability in searchable:
                matches.append(_format_plugin(name, info))
        if matches:
            send(sender, f"Plugins matching '{capability}':\n" + "\n".join(f"  {m}" for m in matches))
        else:
            send(sender, f"no plugins found matching '{capability}'")


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _load_cache()
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
