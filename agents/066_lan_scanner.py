#!/usr/bin/env python3
"""Agent 066 — LAN Scanner
Role: Scans the LAN for devices running Agent Mesh.
Listens for: scan_lan, lan_devices
Emits: device lists, scan results
"""
import os, sys, json, time, socket, ipaddress
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_066_lan_scanner"
AGENT_NAME = "Agent 066 — LAN Scanner"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

LAN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "lan_devices.json"
)
AGENT_MESH_PORTS = [8765, 8766]
SCAN_TIMEOUT = 0.5  # seconds per port


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


def _get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_subnet():
    """Determine local /24 subnet from our IP."""
    local_ip = _get_local_ip()
    try:
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return str(network)
    except Exception:
        return "192.168.1.0/24"


def _check_port(host, port, timeout=SCAN_TIMEOUT):
    """Check if a port is open. Returns True/False."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def _scan_subnet(subnet_cidr):
    """Scan all hosts in subnet for agent mesh ports. Returns list of found devices."""
    found = []
    try:
        network = ipaddress.IPv4Network(subnet_cidr, strict=False)
    except Exception as e:
        print(f"[{AGENT_ID}] invalid subnet: {e}")
        return found

    hosts = list(network.hosts())
    print(f"[{AGENT_ID}] scanning {len(hosts)} hosts on {subnet_cidr}...")
    local_ip = _get_local_ip()

    for host in hosts:
        ip = str(host)
        open_ports = []
        for port in AGENT_MESH_PORTS:
            if _check_port(ip, port):
                open_ports.append(port)
        if open_ports:
            is_self = (ip == local_ip)
            entry = {
                "ip": ip,
                "open_ports": open_ports,
                "is_self": is_self,
                "has_http": 8765 in open_ports,
                "has_ws": 8766 in open_ports,
                "http_url": f"http://{ip}:8765" if 8765 in open_ports else None,
                "ws_url": f"ws://{ip}:8766" if 8766 in open_ports else None,
                "last_seen": time.time(),
            }
            # Try health check
            if 8765 in open_ports:
                try:
                    r = requests.get(f"http://{ip}:8765/api/health", timeout=2)
                    if r.status_code == 200:
                        entry["health"] = r.json()
                        entry["confirmed_agent_mesh"] = True
                    else:
                        entry["confirmed_agent_mesh"] = False
                except Exception:
                    entry["confirmed_agent_mesh"] = False
            found.append(entry)
            print(f"[{AGENT_ID}] found: {ip} ports={open_ports}")
    return found


def _save_devices(devices):
    try:
        with open(LAN_FILE, "w") as f:
            json.dump({
                "scan_time": time.time(),
                "scan_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "subnet": _get_subnet(),
                "devices": devices,
            }, f, indent=2, default=str)
    except Exception as e:
        print(f"[{AGENT_ID}] save error: {e}")


def _load_devices():
    if not os.path.exists(LAN_FILE):
        return {}
    try:
        with open(LAN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


_last_scan = {}


def run_cycle():
    global _last_scan
    subnet = _get_subnet()
    print(f"[{AGENT_ID}] starting LAN scan on {subnet}")
    devices = _scan_subnet(subnet)
    _last_scan = {
        "scan_time": time.time(),
        "subnet": subnet,
        "devices": devices,
        "count": len(devices),
    }
    _save_devices(devices)
    print(f"[{AGENT_ID}] scan complete — {len(devices)} agent mesh devices found")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "scan_lan":
        subnet = _get_subnet()
        send(sender, f"scanning {subnet} — this may take up to 30s...")
        devices = _scan_subnet(subnet)
        _save_devices(devices)
        confirmed = [d for d in devices if d.get("confirmed_agent_mesh")]
        send(sender, json.dumps({
            "subnet": subnet,
            "total_found": len(devices),
            "confirmed_agent_mesh": len(confirmed),
            "devices": devices,
        }))

    elif text == "lan_devices":
        cached = _load_devices()
        if not cached:
            send(sender, json.dumps({"error": "no scan data yet — run 'scan_lan' first"}))
            return
        age = round(time.time() - cached.get("scan_time", 0), 0)
        cached["age_seconds"] = age
        send(sender, json.dumps(cached))


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
        time.sleep(600)


if __name__ == "__main__":
    main()
