#!/usr/bin/env python3
"""Agent 061 — mDNS Advertiser
Role: Advertises the broker on LAN via mDNS so other devices find it automatically.
Listens for: advertise_start, advertise_stop, mdns_status
Emits: advertising status replies
"""
import os, sys, json, time, socket
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_061_mdns_advertiser"
AGENT_NAME = "Agent 061 — mDNS Advertiser"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

MDNS_SERVICE_TYPE = "_agent-mesh._tcp.local."
BROKER_HTTP_PORT = 8765
BROKER_WS_PORT = 8766

try:
    from zeroconf import Zeroconf, ServiceInfo
    HAS_ZEROCONF = True
except Exception:
    HAS_ZEROCONF = False

_zeroconf = None
_service_info = None
_advertising = False


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


def _get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _start_advertising():
    global _zeroconf, _service_info, _advertising
    if not HAS_ZEROCONF:
        return False
    try:
        local_ip = _get_local_ip()
        hostname = socket.gethostname()
        service_name = f"{hostname}.{MDNS_SERVICE_TYPE}"
        _service_info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=BROKER_WS_PORT,
            properties={
                "http_port": str(BROKER_HTTP_PORT),
                "ws_port": str(BROKER_WS_PORT),
                "host": hostname,
            },
            server=f"{hostname}.local.",
        )
        _zeroconf = Zeroconf()
        _zeroconf.register_service(_service_info)
        _advertising = True
        print(f"[{AGENT_ID}] mDNS advertising started: {service_name} @ {local_ip}:{BROKER_WS_PORT}")
        return True
    except Exception as e:
        print(f"[{AGENT_ID}] mDNS start error: {e}")
        _advertising = False
        return False


def _stop_advertising():
    global _zeroconf, _service_info, _advertising
    if _zeroconf and _service_info:
        try:
            _zeroconf.unregister_service(_service_info)
            _zeroconf.close()
        except Exception as e:
            print(f"[{AGENT_ID}] mDNS stop error: {e}")
    _zeroconf = None
    _service_info = None
    _advertising = False
    print(f"[{AGENT_ID}] mDNS advertising stopped")


def run_cycle():
    if not HAS_ZEROCONF:
        print(f"[{AGENT_ID}] zeroconf not installed. Install with: pip install zeroconf")
        print(f"[{AGENT_ID}] mDNS advertising unavailable until zeroconf is installed.")
        return

    if not _advertising:
        print(f"[{AGENT_ID}] starting mDNS advertising...")
        _start_advertising()
    else:
        local_ip = _get_local_ip()
        print(f"[{AGENT_ID}] mDNS advertising active — broker @ {local_ip}:{BROKER_WS_PORT}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "advertise_start":
        if not HAS_ZEROCONF:
            send(sender, "zeroconf not installed. Run: pip install zeroconf")
            return
        if _advertising:
            send(sender, "mDNS advertising already active")
            return
        ok = _start_advertising()
        if ok:
            local_ip = _get_local_ip()
            send(sender, f"mDNS advertising started — broker @ {local_ip}:{BROKER_WS_PORT} on {MDNS_SERVICE_TYPE}")
        else:
            send(sender, "mDNS advertising failed to start — check logs")

    elif text == "advertise_stop":
        if not _advertising:
            send(sender, "mDNS advertising is not active")
            return
        _stop_advertising()
        send(sender, "mDNS advertising stopped")

    elif text == "mdns_status":
        if not HAS_ZEROCONF:
            send(sender, json.dumps({
                "advertising": False,
                "has_zeroconf": False,
                "install_cmd": "pip install zeroconf",
            }))
            return
        local_ip = _get_local_ip()
        hostname = socket.gethostname()
        info = {
            "advertising": _advertising,
            "has_zeroconf": True,
            "service_type": MDNS_SERVICE_TYPE,
            "broker_ip": local_ip if _advertising else None,
            "broker_ws_port": BROKER_WS_PORT if _advertising else None,
            "broker_http_port": BROKER_HTTP_PORT if _advertising else None,
            "hostname": hostname,
        }
        send(sender, json.dumps(info))


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
