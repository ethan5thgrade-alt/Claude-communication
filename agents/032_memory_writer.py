#!/usr/bin/env python3
"""Agent 032 — Memory Writer
Role: Writes validated memory entries with proper schema.
Listens for: remember <key> <value> [type], remember_session <key> <value>, bulk_remember <json_array>
Emits: write confirmations
"""
import os, sys, json, time, datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_032_memory_writer"
AGENT_NAME = "Agent 032 — Memory Writer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

VALID_TYPES = {"fact", "decision", "context", "contract", "preference", "warning"}
DEFAULT_TYPE = "fact"


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


def write_memory(key, value, mem_type=DEFAULT_TYPE):
    """POST to /api/memory with validation."""
    if not key or not key.strip():
        return None, "key cannot be empty"
    if value is None:
        return None, "value cannot be null"
    if mem_type not in VALID_TYPES:
        mem_type = DEFAULT_TYPE

    result = api("/api/memory", "POST", {
        "key": key.strip(),
        "value": value,
        "mem_type": mem_type,
    })
    return result, None


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("remember "):
        # remember <key> <value> [type]
        rest = text[len("remember "):].strip()
        parts = rest.split(" ", 2)
        if len(parts) < 2:
            send(sender, "usage: remember <key> <value> [type]")
            return
        key = parts[0]
        if len(parts) == 3:
            # check if last token is a valid type
            possible_value, possible_type = parts[1], parts[2]
            # Actually: key value type OR key "long value"
            # Simple heuristic: last token is type if it's in VALID_TYPES
            if possible_type in VALID_TYPES:
                value, mem_type = possible_value, possible_type
            else:
                # treat parts[1] + parts[2] as the value
                value = parts[1] + " " + parts[2]
                mem_type = DEFAULT_TYPE
        else:
            value = parts[1]
            mem_type = DEFAULT_TYPE

        result, err = write_memory(key, value, mem_type)
        if err:
            send(sender, f"error: {err}")
        else:
            send(sender, f"remembered: key={key} type={mem_type}")

    elif text.startswith("remember_session "):
        rest = text[len("remember_session "):].strip()
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            send(sender, "usage: remember_session <key> <value>")
            return
        key = "tmp:" + parts[0]
        value = parts[1]
        result, err = write_memory(key, value, "context")
        if err:
            send(sender, f"error: {err}")
        else:
            send(sender, f"session memory written: key={key} (expires ~24h)")

    elif text.startswith("bulk_remember "):
        raw = text[len("bulk_remember "):].strip()
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError("expected JSON array")
        except Exception as e:
            send(sender, f"error: invalid JSON — {e}")
            return
        written = []
        errors = []
        for item in items:
            key = item.get("key", "")
            value = item.get("value")
            mem_type = item.get("type", DEFAULT_TYPE)
            result, err = write_memory(key, value, mem_type)
            if err:
                errors.append({"key": key, "error": err})
            else:
                written.append(key)
        send(sender, f"bulk_remember: written={written} errors={errors}")


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
