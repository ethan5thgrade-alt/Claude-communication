#!/usr/bin/env python3
"""Agent 067 — Port Manager
Role: Manages port allocation and checks for conflicts.
Listens for: port_status, check_port <port>, find_free_port <start>
Emits: port status reports, conflict alerts
"""
import os, sys, json, time, socket, subprocess
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_067_port_manager"
AGENT_NAME = "Agent 067 — Port Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

BROKER_PORTS = [8765, 8766]


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


def _port_in_use(port):
    """Check if a port is in use."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(("localhost", port))
        s.close()
        return result == 0
    except Exception:
        return False


def _get_port_process_psutil(port):
    """Use psutil to find what process owns a port."""
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                pid = conn.pid
                if pid:
                    try:
                        proc = psutil.Process(pid)
                        return {"pid": pid, "name": proc.name(), "cmdline": " ".join(proc.cmdline()[:3])}
                    except Exception:
                        return {"pid": pid, "name": "unknown"}
        return None
    except ImportError:
        return None


def _get_port_process_lsof(port):
    """Fall back to lsof if psutil is not available."""
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            if len(parts) >= 2:
                return {"pid": parts[1], "name": parts[0], "cmdline": " ".join(parts[:3])}
        return None
    except Exception:
        return None


def _get_port_info(port):
    """Get process info for a port using psutil or lsof."""
    in_use = _port_in_use(port)
    if not in_use:
        return {"port": port, "in_use": False}
    process = _get_port_process_psutil(port) or _get_port_process_lsof(port)
    return {
        "port": port,
        "in_use": True,
        "process": process,
    }


def _is_broker_port(port, process_info):
    """Check if a port is owned by the broker process."""
    if not process_info:
        return False
    proc = process_info.get("process", {})
    if not proc:
        return False
    cmdline = proc.get("cmdline", "")
    return "broker.py" in cmdline or "broker" in proc.get("name", "").lower()


def _find_free_port(start):
    """Find the next available port from start."""
    port = start
    while port < start + 1000:
        if not _port_in_use(port):
            return port
        port += 1
    return None


def run_cycle():
    conflicts = []
    for port in BROKER_PORTS:
        info = _get_port_info(port)
        if info["in_use"]:
            is_broker = _is_broker_port(port, info)
            if not is_broker:
                process = info.get("process", {})
                conflicts.append({
                    "port": port,
                    "conflicting_process": process,
                })
                broadcast(f"[port_manager] CONFLICT: port {port} is used by {process.get('name', 'unknown')} (not broker)")
            else:
                print(f"[{AGENT_ID}] port {port}: in use by broker (OK)")
        else:
            print(f"[{AGENT_ID}] port {port}: free (broker may be down)")

    if not conflicts:
        print(f"[{AGENT_ID}] no port conflicts detected")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "port_status":
        results = {}
        for port in BROKER_PORTS:
            info = _get_port_info(port)
            results[str(port)] = info
        send(sender, json.dumps({"ports": results}))

    elif text.startswith("check_port "):
        try:
            port = int(text.split(" ", 1)[1].strip())
        except ValueError:
            send(sender, "usage: check_port <port>")
            return
        info = _get_port_info(port)
        if info["in_use"]:
            proc = info.get("process", {})
            send(sender, json.dumps({
                "port": port,
                "available": False,
                "process": proc,
            }))
        else:
            send(sender, json.dumps({"port": port, "available": True}))

    elif text.startswith("find_free_port "):
        try:
            start = int(text.split(" ", 1)[1].strip())
        except ValueError:
            send(sender, "usage: find_free_port <start>")
            return
        free = _find_free_port(start)
        if free:
            send(sender, json.dumps({"free_port": free, "searched_from": start}))
        else:
            send(sender, json.dumps({"error": f"no free port found from {start} to {start + 1000}"}))


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
        time.sleep(300)


if __name__ == "__main__":
    main()
