#!/usr/bin/env python3
"""Agent 069 — Firewall Advisor
Role: Detects firewall issues and provides fix instructions.
Listens for: firewall_check, firewall_fix_macos, firewall_fix_linux
Emits: firewall status, fix instructions
"""
import os, sys, json, time, socket, subprocess
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_069_firewall_advisor"
AGENT_NAME = "Agent 069 — Firewall Advisor"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

BROKER_HTTP_PORT = 8765
BROKER_WS_PORT = 8766
TEST_OUTBOUND_HOST = "8.8.8.8"
TEST_OUTBOUND_PORT = 53


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


def _test_local_port(port, timeout=3.0):
    """Test if a local port accepts connections."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        return result == 0
    except Exception:
        return False


def _test_outbound(host=TEST_OUTBOUND_HOST, port=TEST_OUTBOUND_PORT, timeout=3.0):
    """Test outbound connectivity."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def _test_broker_http():
    """Test broker HTTP endpoint."""
    try:
        r = requests.get(f"http://localhost:{BROKER_HTTP_PORT}/api/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _run_firewall_checks():
    """Run all connectivity checks. Returns dict of results."""
    return {
        "broker_http_reachable": _test_broker_http(),
        "broker_http_port_open": _test_local_port(BROKER_HTTP_PORT),
        "broker_ws_port_open": _test_local_port(BROKER_WS_PORT),
        "outbound_internet": _test_outbound(),
    }


def run_cycle():
    checks = _run_firewall_checks()
    blocked = [k for k, v in checks.items() if not v]
    if blocked:
        print(f"[{AGENT_ID}] potential firewall issues: {blocked}")
        broadcast(f"[firewall_advisor] connectivity issues detected: {blocked}")
    else:
        print(f"[{AGENT_ID}] all connectivity checks passed")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "firewall_check":
        checks = _run_firewall_checks()
        blocked = [k for k, v in checks.items() if not v]
        ok = len(blocked) == 0
        send(sender, json.dumps({
            "overall": "pass" if ok else "fail",
            "checks": checks,
            "blocked": blocked,
            "recommendation": (
                "All clear" if ok else
                f"Possible firewall blocking: {', '.join(blocked)}. "
                "Try 'firewall_fix_macos' or 'firewall_fix_linux' for fix instructions."
            ),
        }))

    elif text == "firewall_fix_macos":
        reply = (
            "macOS Firewall Fix Instructions:\n\n"
            "Option 1: Allow Python/broker via System Settings:\n"
            "  System Settings -> Network -> Firewall -> Options\n"
            "  Add Python (or your broker binary) and set 'Allow incoming connections'\n\n"
            "Option 2: Temporarily disable macOS firewall (for dev only):\n"
            "  sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate off\n\n"
            "Option 3: Allow specific ports via pfctl:\n"
            f"  echo 'pass in proto tcp from any to any port {{{BROKER_HTTP_PORT},{BROKER_WS_PORT}}}' | sudo pfctl -f -\n"
            "  sudo pfctl -e\n\n"
            "Option 4: Allow via ipfw (older macOS):\n"
            f"  sudo ipfw add allow tcp from any to any dst-port {BROKER_HTTP_PORT}\n"
            f"  sudo ipfw add allow tcp from any to any dst-port {BROKER_WS_PORT}\n\n"
            "Re-enable macOS firewall after testing:\n"
            "  sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on"
        )
        send(sender, reply)

    elif text == "firewall_fix_linux":
        reply = (
            "Linux Firewall Fix Instructions:\n\n"
            "UFW (Ubuntu/Debian):\n"
            f"  sudo ufw allow {BROKER_HTTP_PORT}/tcp\n"
            f"  sudo ufw allow {BROKER_WS_PORT}/tcp\n"
            "  sudo ufw reload\n"
            "  sudo ufw status\n\n"
            "iptables:\n"
            f"  sudo iptables -A INPUT -p tcp --dport {BROKER_HTTP_PORT} -j ACCEPT\n"
            f"  sudo iptables -A INPUT -p tcp --dport {BROKER_WS_PORT} -j ACCEPT\n"
            "  sudo iptables-save | sudo tee /etc/iptables/rules.v4\n\n"
            "firewalld (RHEL/CentOS/Fedora):\n"
            f"  sudo firewall-cmd --permanent --add-port={BROKER_HTTP_PORT}/tcp\n"
            f"  sudo firewall-cmd --permanent --add-port={BROKER_WS_PORT}/tcp\n"
            "  sudo firewall-cmd --reload\n\n"
            "Check current rules:\n"
            "  sudo ufw status verbose   # or:\n"
            "  sudo iptables -L -n -v\n"
            "  sudo firewall-cmd --list-all"
        )
        send(sender, reply)


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
