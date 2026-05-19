#!/usr/bin/env python3
"""Agent 062 — mDNS Browser
Role: Discovers other brokers on the LAN via mDNS browsing.
Listens for: discover, discovered_brokers, connect_to <broker_ip>
Emits: discovered broker lists
"""
import os, sys, json, time, socket
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_062_mdns_browser"
AGENT_NAME = "Agent 062 — mDNS Browser"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

MDNS_SERVICE_TYPE = "_agent-mesh._tcp.local."
DISCOVERED_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "discovered_brokers.json")

# Cache: {name: {ip, port, last_seen, service_name}}
_discovered = {}


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


def _save_discovered():
    try:
        with open(DISCOVERED_FILE, "w") as f:
            json.dump(_discovered, f, indent=2, default=str)
    except Exception as e:
        print(f"[{AGENT_ID}] save error: {e}")


def _load_discovered():
    global _discovered
    if os.path.exists(DISCOVERED_FILE):
        try:
            with open(DISCOVERED_FILE) as f:
                _discovered = json.load(f)
        except Exception:
            _discovered = {}


def _browse_mdns(timeout=5.0):
    """Browse mDNS for _agent-mesh._tcp.local. services. Returns list of discovered brokers."""
    found = []
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except Exception:
        print(f"[{AGENT_ID}] zeroconf not installed — install with: pip install zeroconf")
        return found

    class _Listener(ServiceListener):
        def add_service(self, zc, type_, name):
            try:
                info = zc.get_service_info(type_, name, timeout=1500)
            except Exception:
                return
            if not info:
                return
            host = None
            try:
                addrs = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
                if addrs:
                    host = addrs[0]
            except Exception:
                pass
            if not host:
                try:
                    raw = info.addresses[0] if info.addresses else b""
                    host = socket.inet_ntoa(raw) if len(raw) == 4 else None
                except Exception:
                    pass
            port = int(info.port) if info.port else 8766
            label = name
            if label.endswith("." + MDNS_SERVICE_TYPE):
                label = label[:-(len(MDNS_SERVICE_TYPE) + 1)]
            if host:
                found.append({
                    "name": label,
                    "ip": host,
                    "port": port,
                    "ws_url": f"ws://{host}:{port}",
                    "http_url": f"http://{host}:8765",
                    "last_seen": time.time(),
                })

        def update_service(self, zc, type_, name):
            pass

        def remove_service(self, zc, type_, name):
            pass

    zc = None
    try:
        zc = Zeroconf()
        ServiceBrowser(zc, MDNS_SERVICE_TYPE, _Listener())
        time.sleep(timeout)
    except Exception as e:
        print(f"[{AGENT_ID}] browse error: {e}")
    finally:
        try:
            if zc:
                zc.close()
        except Exception:
            pass
    return found


def run_cycle():
    global _discovered
    print(f"[{AGENT_ID}] browsing mDNS for agent mesh brokers...")
    results = _browse_mdns(timeout=5.0)
    now = time.time()
    for broker in results:
        key = broker["ip"]
        _discovered[key] = broker
    # Mark stale entries (not seen in 10 minutes)
    for key in list(_discovered.keys()):
        last = _discovered[key].get("last_seen", 0)
        if now - last > 600:
            _discovered[key]["status"] = "stale"
        else:
            _discovered[key]["status"] = "active"
    _save_discovered()
    print(f"[{AGENT_ID}] discovered {len(results)} brokers, total cached: {len(_discovered)}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "discover":
        print(f"[{AGENT_ID}] immediate mDNS browse requested by {sender}")
        results = _browse_mdns(timeout=3.0)
        now = time.time()
        for broker in results:
            _discovered[broker["ip"]] = broker
        _save_discovered()
        reply = json.dumps({
            "discovered": results,
            "count": len(results),
            "cached_total": len(_discovered),
        })
        send(sender, reply)

    elif text == "discovered_brokers":
        _load_discovered()
        now = time.time()
        brokers_with_age = []
        for ip, info in _discovered.items():
            entry = dict(info)
            last = entry.get("last_seen", 0)
            entry["age_seconds"] = round(now - last, 1)
            entry["last_seen_iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last))
            brokers_with_age.append(entry)
        send(sender, json.dumps({"brokers": brokers_with_age, "count": len(brokers_with_age)}))

    elif text.startswith("connect_to "):
        broker_ip = text[len("connect_to "):].strip()
        broker_port = 8766
        # Look up port from cache
        if broker_ip in _discovered:
            broker_port = _discovered[broker_ip].get("port", 8766)
        ws_url = f"ws://{broker_ip}:{broker_port}"
        http_url = f"http://{broker_ip}:8765"
        reply = (
            f"To connect to broker at {broker_ip}:\n"
            f"  export BROKER_URL={ws_url}\n"
            f"  python3 connect.py\n"
            f"Or via CLI:\n"
            f"  BROKER_URL={ws_url} python3 cli.py status\n"
            f"HTTP API: {http_url}/api/health"
        )
        send(sender, reply)


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _load_discovered()
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(120)


if __name__ == "__main__":
    main()
