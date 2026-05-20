#!/usr/bin/env python3
"""Agent 070 — Latency Monitor
Role: Tracks round-trip latency between all connected instances.
Listens for: ping <instance_id>, latency_report, slowest_instances, latency_history <instance_id>
Emits: pong responses, latency stats
"""
import os, sys, json, time
from collections import defaultdict, deque
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_070_latency_monitor"
AGENT_NAME = "Agent 070 — Latency Monitor"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Latency history per instance: {instance_id: deque of (ts, rtt_ms)}
_latency_history = defaultdict(lambda: deque(maxlen=200))
# Pending pings: {ping_id: (instance_id, sent_ts)}
_pending_pings = {}
_ping_counter = 0


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


def _percentile(data, p):
    """Compute percentile p (0-100) of a sorted list."""
    if not data:
        return 0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def _compute_stats(rtts):
    if not rtts:
        return {"p50": 0, "p95": 0, "p99": 0, "max": 0, "min": 0, "avg": 0, "count": 0}
    return {
        "p50": round(_percentile(rtts, 50), 2),
        "p95": round(_percentile(rtts, 95), 2),
        "p99": round(_percentile(rtts, 99), 2),
        "max": round(max(rtts), 2),
        "min": round(min(rtts), 2),
        "avg": round(sum(rtts) / len(rtts), 2),
        "count": len(rtts),
    }


def _ping_instance(instance_id):
    """Send a ping message to an instance and record the send time.

    Returns RTT in ms by using the broker REST API round-trip as proxy.
    For a real WebSocket RTT measurement we approximate using HTTP send + health timing.
    """
    global _ping_counter
    _ping_counter += 1
    ping_id = f"ping_{_ping_counter}_{int(time.time())}"
    t0 = time.time()
    # Send ping via REST API
    result = api("/api/send", "POST", {
        "to": instance_id,
        "from": AGENT_ID,
        "text": f"__ping__ {ping_id}",
        "room": ROOM,
    })
    t1 = time.time()
    # Use the round-trip of the REST API call itself as proxy RTT
    rtt_ms = round((t1 - t0) * 1000, 2)
    return ping_id, rtt_ms


def run_cycle():
    """Ping each online instance and record RTT."""
    result = api("/api/instances")
    instances = result.get("instances", []) if isinstance(result, dict) else []
    online = [i for i in instances if i.get("online") and i.get("id") != AGENT_ID]

    for inst in online:
        inst_id = inst.get("id", "")
        if not inst_id:
            continue
        try:
            ping_id, rtt_ms = _ping_instance(inst_id)
            _latency_history[inst_id].append((time.time(), rtt_ms))
            print(f"[{AGENT_ID}] ping {inst_id}: {rtt_ms}ms")
        except Exception as e:
            print(f"[{AGENT_ID}] ping {inst_id} error: {e}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    # Handle pong responses (instances reply to __ping__ messages)
    if text.startswith("__pong__ "):
        # ping_id embedded in pong, but we use REST round-trip so just ignore
        return

    if text.startswith("ping "):
        instance_id = text[len("ping "):].strip()
        try:
            ping_id, rtt_ms = _ping_instance(instance_id)
            _latency_history[instance_id].append((time.time(), rtt_ms))
            send(sender, json.dumps({
                "instance": instance_id,
                "rtt_ms": rtt_ms,
                "ping_id": ping_id,
                "note": "RTT measured via broker REST round-trip",
            }))
        except Exception as e:
            send(sender, f"ping error: {e}")

    elif text == "latency_report":
        report = {}
        for inst_id, history in _latency_history.items():
            rtts = [rtt for _, rtt in history]
            report[inst_id] = _compute_stats(rtts)
        send(sender, json.dumps({"latency_report": report, "instance_count": len(report)}))

    elif text == "slowest_instances":
        ranked = []
        for inst_id, history in _latency_history.items():
            rtts = [rtt for _, rtt in history]
            if rtts:
                stats = _compute_stats(rtts)
                ranked.append({"instance": inst_id, "p95_ms": stats["p95"], "avg_ms": stats["avg"]})
        ranked.sort(key=lambda x: -x["p95_ms"])
        top3 = ranked[:3]
        send(sender, json.dumps({"slowest_instances": top3}))

    elif text.startswith("latency_history "):
        instance_id = text[len("latency_history "):].strip()
        history = list(_latency_history.get(instance_id, []))
        data = [{"ts": ts, "rtt_ms": rtt} for ts, rtt in history]
        rtts = [rtt for _, rtt in history]
        send(sender, json.dumps({
            "instance": instance_id,
            "history": data,
            "count": len(data),
            "stats": _compute_stats(rtts),
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
