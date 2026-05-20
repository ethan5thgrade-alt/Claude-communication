#!/usr/bin/env python3
"""Agent 092 — Token Rotator
Role: Rotates the MESH_TOKEN security token on schedule (every 7 days).
"""
import os, sys, json, time, requests, datetime, secrets
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_092_token_rotator"
AGENT_NAME = "Agent 092 — Token Rotator"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

TOKEN_FILE = os.path.expanduser("~/.agent-mesh-inbox/.mesh_token")
TOKEN_CREATED_FILE = os.path.expanduser("~/.agent-mesh-inbox/.mesh_token_created")
TOKEN_MAX_AGE_DAYS = 7


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


def _token_age_days():
    try:
        with open(TOKEN_CREATED_FILE) as f:
            created_str = f.read().strip()
        created = datetime.datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - created).days
    except Exception:
        return 0


def _generate_token():
    return secrets.token_hex(32)


def _write_token(new_token):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(new_token)
    with open(TOKEN_CREATED_FILE, "w") as f:
        f.write(datetime.datetime.now(datetime.timezone.utc).isoformat())


def _do_rotation():
    new_token = _generate_token()
    _write_token(new_token)
    # Broadcast new token with grace period notice
    broadcast(f"[TOKEN ROTATION] New MESH_TOKEN being distributed. "
              f"Grace period: 60 seconds. New token: {new_token[:8]}... "
              f"(full token written to {TOKEN_FILE})")
    print(f"[{AGENT_ID}] token rotated, written to {TOKEN_FILE}")
    time.sleep(60)  # grace period
    send("all", f"[TOKEN ROTATION COMPLETE] Token has been updated. "
                f"Reconnect using the new token from {TOKEN_FILE}")
    return new_token


def run_cycle():
    """Every 24 hours: check token age. If >7 days, rotate."""
    age = _token_age_days()
    if age >= TOKEN_MAX_AGE_DAYS:
        print(f"[{AGENT_ID}] token is {age} days old — rotating")
        _do_rotation()
    else:
        print(f"[{AGENT_ID}] token age: {age} days (max {TOKEN_MAX_AGE_DAYS})")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "rotate_now":
        send(sender, "Initiating immediate token rotation...")
        new_token = _do_rotation()
        send(sender, f"Token rotated. New token written to {TOKEN_FILE}.")

    elif text == "token_age":
        age = _token_age_days()
        try:
            with open(TOKEN_CREATED_FILE) as f:
                created = f.read().strip()
        except FileNotFoundError:
            created = "unknown"
        send(sender, f"Token age: {age} days (created: {created}). "
                     f"Max age: {TOKEN_MAX_AGE_DAYS} days before rotation.")

    elif text.startswith("broadcast_token "):
        new_token = text[len("broadcast_token "):].strip()
        if not new_token:
            send(sender, "Usage: broadcast_token <new_token>")
            return
        _write_token(new_token)
        broadcast(f"[TOKEN UPDATE] New MESH_TOKEN distributed by {sender}. "
                  f"Update your MESH_TOKEN env var. Token prefix: {new_token[:8]}...")
        send(sender, f"New token broadcast to all instances and written to {TOKEN_FILE}.")


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
        time.sleep(86400)


if __name__ == "__main__":
    main()
