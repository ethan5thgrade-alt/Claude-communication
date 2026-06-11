"""Multi-device smoke test — proves the 2-friends-2-devices flow works.

Simulates two devices joining the same broker. Run against a live broker:

    python3 examples/multi_device_smoke.py

What it tests:
  1. /api/share-info advertises a routable URL (LAN or public)
  2. A simulated "remote" instance can register over WebSocket
  3. A simulated "second remote" can also register
  4. They each see the other in /api/instances
  5. A message from one is routed to the other's WS

What it does NOT test:
  - Actual network reachability across machines (single-host simulation)
  - LLM bot replies

Zero LLM cost — pure protocol exercise.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import urllib.request

import websockets

BASE_HTTP = os.environ.get("MESH_HTTP", "http://localhost:8765")
BASE_WS = os.environ.get("MESH_WS", "ws://localhost:8766")


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_HTTP}{path}", timeout=5) as r:
        return json.load(r)


async def register(ws, iid: str, name: str, room: str = "smoke") -> None:
    await ws.send(json.dumps({
        "type": "register",
        "id": iid, "name": name,
        "project": "multi-device-smoke",
        "email": f"{iid}@example.com",
        "role": "tester",
        "room": room,
    }))


async def recv_with_timeout(ws, timeout: float = 3.0):
    try:
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
        return None


async def main() -> int:
    print(f"broker HTTP: {BASE_HTTP}")
    print(f"broker WS:   {BASE_WS}")
    print()

    # ---- check share-info ----
    info = get("/api/share-info")
    print(f"  share-info advertises:")
    print(f"    http_url = {info.get('http_url')}")
    print(f"    ws_url   = {info.get('ws_url')}")
    print(f"    token    = {info.get('token') or '(none)'}")
    if not info.get("http_url") or "localhost" in str(info.get("http_url", "")):
        print("  warning: http_url is localhost — friend on different device cannot reach it.")
        print("     For LAN: bind to 0.0.0.0 (broker already does), share LAN IP manually.")
        print("     For internet: expose port 8766 via a cloudflared tunnel.")
    print()

    # ---- simulate two remote devices ----
    async with websockets.connect(BASE_WS) as ws_a, \
               websockets.connect(BASE_WS) as ws_b:
        print("  both WS connections opened")

        await register(ws_a, "device-a", "Friend A")
        await register(ws_b, "device-b", "Friend B")
        # Drain init payloads (memory_init, tasks_init, etc.)
        for ws in (ws_a, ws_b):
            for _ in range(5):
                msg = await recv_with_timeout(ws, 0.5)
                if msg is None:
                    break

        # confirm both visible in /api/instances
        await asyncio.sleep(0.5)
        instances = get("/api/instances")
        ids = {i["id"]: i.get("online") for i in instances}
        for needed in ("device-a", "device-b"):
            if not ids.get(needed):
                print(f"  ✗ {needed} not online in /api/instances: {ids}")
                return 1
        print(f"  both devices registered and online")

        # ---- A sends to B; B should receive it on its WS ----
        await ws_a.send(json.dumps({
            "type": "message",
            "to": "device-b",
            "text": "hello from device-a",
        }))
        msg = await recv_with_timeout(ws_b, timeout=3)
        if not msg or msg.get("type") != "message" or msg.get("text") != "hello from device-a":
            print(f"  ✗ device-b did not receive A's message; got: {msg}")
            return 1
        print(f"  device-b received A's message via WS ✓")

        # ---- B replies; A should receive it ----
        await ws_b.send(json.dumps({
            "type": "message",
            "to": "device-a",
            "text": "ack from device-b",
        }))
        msg = await recv_with_timeout(ws_a, timeout=3)
        if not msg or msg.get("type") != "message" or msg.get("text") != "ack from device-b":
            print(f"  ✗ device-a did not receive B's reply; got: {msg}")
            return 1
        print(f"  device-a received B's reply via WS ✓")

    print()
    print("=== PASS: 2-device flow works against this broker ===")
    print("To do this for real across two machines:")
    print(f"  Friend A: python3 broker.py    (already running on {info.get('http_url')})")
    print(f"  Friend B: BROKER_URL={info.get('ws_url')} python3 mesh-connect.py")
    print("  Both: open the dashboard at the http_url above")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
