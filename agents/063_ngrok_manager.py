#!/usr/bin/env python3
"""Agent 063 — Ngrok Manager
Role: Manages ngrok tunnels for internet sharing.
Listens for: ngrok_start, ngrok_stop, ngrok_status, ngrok_urls, share_link
Emits: tunnel status, public URLs, join commands
"""
import os, sys, json, time, subprocess
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_063_ngrok_manager"
AGENT_NAME = "Agent 063 — Ngrok Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

NGROK_API = "http://localhost:4040/api/tunnels"
BROKER_HTTP_PORT = 8765
BROKER_WS_PORT = 8766

_last_tunnels = []


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


def _is_ngrok_running():
    result = subprocess.run(["pgrep", "-f", "ngrok"], capture_output=True)
    return result.returncode == 0


def _get_tunnels():
    """Fetch ngrok tunnels from the local API."""
    try:
        r = requests.get(NGROK_API, timeout=5)
        return r.json().get("tunnels", [])
    except Exception:
        return []


def _start_ngrok():
    """Start ngrok tunnels for HTTP (8765) and TCP (8766)."""
    if _is_ngrok_running():
        return True, "ngrok already running"
    try:
        # Start HTTP tunnel for broker REST API
        subprocess.Popen(
            ["ngrok", "http", str(BROKER_HTTP_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        # Start TCP tunnel for WebSocket
        subprocess.Popen(
            ["ngrok", "tcp", str(BROKER_WS_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        return True, "ngrok tunnels started"
    except FileNotFoundError:
        return False, "ngrok not found — install from https://ngrok.com/download"
    except Exception as e:
        return False, f"ngrok start error: {e}"


def _stop_ngrok():
    """Kill all ngrok processes."""
    try:
        subprocess.run(["pkill", "-f", "ngrok"], capture_output=True)
        return True
    except Exception as e:
        print(f"[{AGENT_ID}] stop error: {e}")
        return False


def _format_tunnels(tunnels):
    """Format tunnel info for display."""
    out = []
    for t in tunnels:
        proto = t.get("proto", "?")
        public_url = t.get("public_url", "?")
        local_addr = t.get("config", {}).get("addr", "?")
        out.append({
            "proto": proto,
            "public_url": public_url,
            "local_addr": local_addr,
        })
    return out


def run_cycle():
    global _last_tunnels
    if not _is_ngrok_running():
        print(f"[{AGENT_ID}] ngrok not running")
        return

    tunnels = _get_tunnels()
    _last_tunnels = tunnels
    if tunnels:
        for t in tunnels:
            pub = t.get("public_url", "?")
            local = t.get("config", {}).get("addr", "?")
            print(f"[{AGENT_ID}] tunnel: {pub} -> {local}")
    else:
        print(f"[{AGENT_ID}] ngrok running but no tunnels found")


def handle_message(msg):
    global _last_tunnels
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "ngrok_start":
        ok, msg_text = _start_ngrok()
        if ok:
            time.sleep(3)
            tunnels = _get_tunnels()
            _last_tunnels = tunnels
            formatted = _format_tunnels(tunnels)
            send(sender, json.dumps({"status": "started", "tunnels": formatted}))
        else:
            send(sender, json.dumps({"status": "error", "message": msg_text}))

    elif text == "ngrok_stop":
        ok = _stop_ngrok()
        _last_tunnels = []
        send(sender, "ngrok tunnels stopped" if ok else "error stopping ngrok — check logs")

    elif text == "ngrok_status":
        if not _is_ngrok_running():
            send(sender, json.dumps({"running": False, "tunnels": []}))
            return
        tunnels = _get_tunnels()
        _last_tunnels = tunnels
        send(sender, json.dumps({
            "running": True,
            "tunnels": _format_tunnels(tunnels),
            "count": len(tunnels),
        }))

    elif text == "ngrok_urls":
        if not _is_ngrok_running():
            send(sender, "ngrok is not running — use 'ngrok_start' first")
            return
        tunnels = _get_tunnels()
        _last_tunnels = tunnels
        cmds = []
        for t in tunnels:
            pub = t.get("public_url", "")
            proto = t.get("proto", "")
            if proto == "tcp" and pub:
                # ws URL from tcp tunnel
                ws_url = pub.replace("tcp://", "ws://")
                cmds.append(f"BROKER_URL={ws_url} python3 connect.py")
            elif proto == "https" and pub:
                cmds.append(f"HTTP API: {pub}/api/health")
        send(sender, "\n".join(cmds) if cmds else "no tunnels found — run ngrok_start first")

    elif text == "share_link":
        if not _is_ngrok_running():
            send(sender, "ngrok not running — use 'ngrok_start' first")
            return
        tunnels = _get_tunnels()
        _last_tunnels = tunnels
        tcp_tunnel = next((t for t in tunnels if t.get("proto") == "tcp"), None)
        if not tcp_tunnel:
            send(sender, "no TCP tunnel found — restart ngrok and try again")
            return
        pub = tcp_tunnel.get("public_url", "")
        ws_url = pub.replace("tcp://", "ws://")
        one_liner = (
            f"BROKER_URL={ws_url} INSTANCE_ID=cc2 NAME='Claude 2' python3 connect.py"
        )
        send(sender, f"Share this one-liner with your collaborator:\n  {one_liner}")


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
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
