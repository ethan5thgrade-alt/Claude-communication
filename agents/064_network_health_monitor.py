#!/usr/bin/env python3
"""Agent 064 — Network Health Monitor
Role: Monitors network connectivity between broker and all instances.
Listens for: network_status, connectivity_test, network_report
Emits: latency logs, outage alerts
"""
import os, sys, json, time, socket
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_064_network_health_monitor"
AGENT_NAME = "Agent 064 — Network Health Monitor"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

BROKER_HOST = "localhost"
BROKER_HTTP_PORT = 8765
BROKER_WS_PORT = 8766
LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "network_health.jsonl"
)

# History: list of {ts, latency_ms, http_ok, ws_ok}
_history = []
MAX_HISTORY = 360  # 3h at 30s intervals
_outages = []  # list of {start, end, type}
_in_outage = False
_outage_start = None


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


def _check_http(timeout=5.0):
    """Ping broker HTTP endpoint, return (ok, latency_ms)."""
    t0 = time.time()
    try:
        r = requests.get(f"{BROKER}/api/health", timeout=timeout, headers=HEADERS)
        latency_ms = round((time.time() - t0) * 1000, 1)
        return r.status_code == 200, latency_ms
    except Exception:
        latency_ms = round((time.time() - t0) * 1000, 1)
        return False, latency_ms


def _check_ws_port(timeout=3.0):
    """Check if broker WebSocket port is reachable."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((BROKER_HOST, BROKER_WS_PORT))
        s.close()
        return result == 0
    except Exception:
        return False


def _log_entry(entry):
    """Append a JSON line to the network health log."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"[{AGENT_ID}] log error: {e}")


def run_cycle():
    global _in_outage, _outage_start
    http_ok, latency_ms = _check_http()
    ws_ok = _check_ws_port()
    ts = time.time()
    entry = {
        "ts": ts,
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "latency_ms": latency_ms,
        "http_ok": http_ok,
        "ws_ok": ws_ok,
    }
    _history.append(entry)
    if len(_history) > MAX_HISTORY:
        _history.pop(0)
    _log_entry(entry)

    # Outage detection
    if not http_ok or not ws_ok:
        if not _in_outage:
            _in_outage = True
            _outage_start = ts
            broadcast(f"[network_health] OUTAGE DETECTED — http={http_ok} ws={ws_ok}")
            print(f"[{AGENT_ID}] OUTAGE: http={http_ok} ws={ws_ok}")
        else:
            print(f"[{AGENT_ID}] outage continuing — http={http_ok} ws={ws_ok}")
    else:
        if _in_outage:
            duration = round(ts - (_outage_start or ts), 1)
            _outages.append({
                "start": _outage_start,
                "end": ts,
                "duration_sec": duration,
            })
            _in_outage = False
            _outage_start = None
            broadcast(f"[network_health] OUTAGE RESOLVED — duration {duration}s")
        print(f"[{AGENT_ID}] healthy — latency={latency_ms}ms http=OK ws=OK")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "network_status":
        http_ok, latency_ms = _check_http()
        ws_ok = _check_ws_port()
        send(sender, json.dumps({
            "http_ok": http_ok,
            "ws_ok": ws_ok,
            "latency_ms": latency_ms,
            "broker_http": f"http://{BROKER_HOST}:{BROKER_HTTP_PORT}",
            "broker_ws": f"ws://{BROKER_HOST}:{BROKER_WS_PORT}",
            "in_outage": _in_outage,
        }))

    elif text == "connectivity_test":
        results = {}
        # HTTP health
        http_ok, latency_ms = _check_http(timeout=5.0)
        results["http_health"] = {"pass": http_ok, "latency_ms": latency_ms}
        # WS port
        ws_ok = _check_ws_port(timeout=3.0)
        results["ws_port"] = {"pass": ws_ok}
        # DNS resolution
        try:
            socket.gethostbyname("localhost")
            results["dns"] = {"pass": True}
        except Exception:
            results["dns"] = {"pass": False}
        # Internet
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(("8.8.8.8", 53))
            s.close()
            results["internet"] = {"pass": True}
        except Exception:
            results["internet"] = {"pass": False}

        all_pass = all(v.get("pass") for v in results.values())
        send(sender, json.dumps({
            "overall": "pass" if all_pass else "fail",
            "checks": results,
        }))

    elif text == "network_report":
        if not _history:
            send(sender, json.dumps({"error": "no data yet"}))
            return
        latencies = [h["latency_ms"] for h in _history if h["http_ok"]]
        http_ups = sum(1 for h in _history if h["http_ok"])
        ws_ups = sum(1 for h in _history if h["ws_ok"])
        total = len(_history)
        uptime_pct = round(http_ups / total * 100, 1) if total else 0
        avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0
        recent = _history[-10:]
        send(sender, json.dumps({
            "samples": total,
            "http_uptime_pct": uptime_pct,
            "ws_uptime_pct": round(ws_ups / total * 100, 1) if total else 0,
            "avg_latency_ms": avg_lat,
            "min_latency_ms": min(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
            "outages": len(_outages),
            "recent_samples": recent,
        }))


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
        time.sleep(30)


if __name__ == "__main__":
    main()
