#!/usr/bin/env python3
"""Agent 068 — SSL/TLS Manager
Role: Manages TLS certificate setup for secure connections.
Listens for: generate_cert, cert_status, enable_tls, check_tls <url>
Emits: certificate info, TLS status
"""
import os, sys, json, time, subprocess, socket
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_068_ssl_tls_manager"
AGENT_NAME = "Agent 068 — SSL/TLS Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CERT_DIR = os.path.expanduser("~/.agent-mesh")
CERT_FILE = os.path.join(CERT_DIR, "cert.pem")
KEY_FILE = os.path.join(CERT_DIR, "key.pem")
CERT_DAYS = 365


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


def _get_cert_expiry(cert_path):
    """Get certificate expiry date using openssl."""
    try:
        result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", cert_path],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Output: "notAfter=May 18 12:00:00 2027 GMT"
            line = result.stdout.strip()
            if "=" in line:
                return line.split("=", 1)[1].strip()
        return None
    except Exception:
        return None


def _generate_cert():
    """Generate a self-signed cert for localhost using openssl."""
    os.makedirs(CERT_DIR, exist_ok=True)
    hostname = socket.gethostname()
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:4096",
        "-keyout", KEY_FILE,
        "-out", CERT_FILE,
        "-days", str(CERT_DAYS),
        "-nodes",
        "-subj", f"/CN=localhost/O=AgentMesh/OU=Dev",
        "-addext", f"subjectAltName=DNS:localhost,DNS:{hostname},IP:127.0.0.1",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True, f"certificate generated at {CERT_FILE}"
        return False, f"openssl error: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, "openssl not found — install OpenSSL first"
    except Exception as e:
        return False, f"error: {e}"


def _check_tls_url(url):
    """Test if a broker URL has valid TLS."""
    if url.startswith("ws://"):
        url = url.replace("ws://", "http://")
    elif url.startswith("wss://"):
        url = url.replace("wss://", "https://")
    try:
        import ssl
        r = requests.get(url + "/api/health", timeout=5, verify=True)
        return True, f"TLS valid — status {r.status_code}"
    except requests.exceptions.SSLError as e:
        return False, f"TLS error: {e}"
    except Exception as e:
        return False, f"connection error: {e}"


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "generate_cert":
        ok, message = _generate_cert()
        if ok:
            expiry = _get_cert_expiry(CERT_FILE)
            send(sender, json.dumps({
                "status": "generated",
                "cert": CERT_FILE,
                "key": KEY_FILE,
                "expiry": expiry,
                "message": message,
            }))
        else:
            send(sender, json.dumps({"status": "error", "message": message}))

    elif text == "cert_status":
        exists = os.path.exists(CERT_FILE)
        if not exists:
            send(sender, json.dumps({
                "exists": False,
                "cert_path": CERT_FILE,
                "message": "no certificate found — run 'generate_cert' to create one",
            }))
            return
        expiry = _get_cert_expiry(CERT_FILE)
        stat = os.stat(CERT_FILE)
        send(sender, json.dumps({
            "exists": True,
            "cert_path": CERT_FILE,
            "key_path": KEY_FILE,
            "key_exists": os.path.exists(KEY_FILE),
            "expiry": expiry,
            "size_bytes": stat.st_size,
            "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        }))

    elif text == "enable_tls":
        reply = (
            "To enable TLS in the broker:\n"
            "1. Generate a certificate: send 'generate_cert' to this agent\n"
            "2. Set env vars before starting the broker:\n"
            f"   export MESH_CERT={CERT_FILE}\n"
            f"   export MESH_KEY={KEY_FILE}\n"
            "3. Clients connect with: wss://localhost:8766\n"
            "4. HTTP API becomes: https://localhost:8765\n"
            "Note: Self-signed certs require clients to trust them or disable verification."
        )
        send(sender, reply)

    elif text.startswith("check_tls "):
        url = text[len("check_tls "):].strip()
        ok, message = _check_tls_url(url)
        send(sender, json.dumps({
            "url": url,
            "tls_valid": ok,
            "message": message,
        }))


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    # This agent is reactive only — no periodic cycle needed
    while True:
        time.sleep(300)


if __name__ == "__main__":
    main()
