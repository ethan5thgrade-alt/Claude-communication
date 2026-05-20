#!/usr/bin/env python3
"""Agent 065 — Peer Discovery Agent
Role: Finds and catalogs peer Agent Mesh instances (different deployments).
Listens for: find_peers, add_peer <url>, peer_instances <broker_url>
Emits: peer broker status, instance lists
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_065_peer_discovery_agent"
AGENT_NAME = "Agent 065 — Peer Discovery Agent"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

DISCOVERED_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "discovered_brokers.json"
)

# Peer registry: {url: {url, status, last_checked, instances_count, last_healthy}}
_peers = {}


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


def _check_peer(http_url):
    """Try GET /api/health on a peer broker. Return (ok, data)."""
    try:
        r = requests.get(f"{http_url}/api/health", timeout=5)
        if r.status_code == 200:
            return True, r.json()
    except Exception:
        pass
    return False, {}


def _load_from_discovered():
    """Load peer URLs from the mDNS discovered_brokers.json file."""
    if not os.path.exists(DISCOVERED_FILE):
        return []
    try:
        with open(DISCOVERED_FILE) as f:
            data = json.load(f)
        urls = []
        for ip, info in data.items():
            http_url = info.get("http_url", f"http://{ip}:8765")
            urls.append(http_url)
        return urls
    except Exception:
        return []


def run_cycle():
    # Load peers from discovered_brokers.json
    discovered_urls = _load_from_discovered()
    for url in discovered_urls:
        if url not in _peers:
            _peers[url] = {"url": url, "status": "unknown", "last_checked": 0, "source": "mdns"}

    # Check each peer
    for url in list(_peers.keys()):
        # Skip our own broker
        if "localhost" in url or "127.0.0.1" in url:
            continue
        ok, data = _check_peer(url)
        now = time.time()
        _peers[url]["last_checked"] = now
        if ok:
            _peers[url]["status"] = "online"
            _peers[url]["last_healthy"] = now
            _peers[url]["uptime"] = data.get("uptime_seconds")
        else:
            _peers[url]["status"] = "offline"

    online = sum(1 for p in _peers.values() if p.get("status") == "online")
    print(f"[{AGENT_ID}] peers: {len(_peers)} total, {online} online")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "find_peers":
        discovered = _load_from_discovered()
        for url in discovered:
            if url not in _peers:
                _peers[url] = {"url": url, "status": "unknown", "source": "mdns"}
        # Re-check status
        results = []
        for url, info in _peers.items():
            if "localhost" in url or "127.0.0.1" in url:
                continue
            ok, _ = _check_peer(url)
            status = "online" if ok else "offline"
            _peers[url]["status"] = status
            results.append({"url": url, "status": status, "source": info.get("source", "manual")})
        send(sender, json.dumps({"peers": results, "count": len(results)}))

    elif text.startswith("add_peer "):
        url = text[len("add_peer "):].strip()
        # Normalize to HTTP URL
        if url.startswith("ws://"):
            url = url.replace("ws://", "http://").replace(":8766", ":8765")
        if not url.startswith("http"):
            url = f"http://{url}"
        ok, data = _check_peer(url)
        _peers[url] = {
            "url": url,
            "status": "online" if ok else "offline",
            "last_checked": time.time(),
            "source": "manual",
        }
        status_str = "online" if ok else "offline (unreachable)"
        send(sender, f"peer added: {url} — status: {status_str}")

    elif text.startswith("peer_instances "):
        broker_url = text[len("peer_instances "):].strip()
        if broker_url.startswith("ws://"):
            broker_url = broker_url.replace("ws://", "http://").replace(":8766", ":8765")
        if not broker_url.startswith("http"):
            broker_url = f"http://{broker_url}"
        try:
            r = requests.get(f"{broker_url}/api/instances", timeout=5)
            if r.status_code == 200:
                data = r.json()
                instances = data.get("instances", [])
                send(sender, json.dumps({
                    "broker": broker_url,
                    "instances": instances,
                    "count": len(instances),
                }))
            else:
                send(sender, f"error fetching instances from {broker_url}: HTTP {r.status_code}")
        except Exception as e:
            send(sender, f"failed to reach {broker_url}: {e}")


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
