"""mesh-connect.py — friend-grade connector for Agent Mesh.

Run from a Claude Code session, your terminal, or via:
    python3 <(curl -sL https://raw.githubusercontent.com/ethan5thgrade-alt/Claude-communication/main/mesh-connect.py)

Env vars (all optional except BROKER_URL):
    BROKER_URL      wss://... or ws://...  (REQUIRED — the host gives you this)
    MESH_TOKEN      shared auth token       (REQUIRED if the host set one)
    INSTANCE_ID     your unique id          (default: hostname-pid)
    INSTANCE_NAME   display name            (default: $USER)
    INSTANCE_PROJECT  free-form label       (default: "default")

Interactive mode (default): type a line + Enter to broadcast.
  @<instance_id> text   - direct message that instance
  /quit                 - disconnect and exit

Listen-only mode: pass `--listen` to print incoming and never read stdin.
Send-once mode:   pass `--send "text"` (optionally `--to <id>`) to fire one
                  message and exit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys


def _ensure_websockets():
    try:
        import websockets  # noqa: F401
        return
    except ImportError:
        pass
    print("[setup] installing websockets (one-time)...", file=sys.stderr)
    import subprocess
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--user", "--quiet", "websockets"]
    )


_ensure_websockets()
import websockets  # noqa: E402


def _default_instance_id() -> str:
    host = socket.gethostname().split(".")[0]
    return f"{host}-{os.getpid()}"


BROKER_URL = os.environ.get("BROKER_URL", "").strip()
MESH_TOKEN = os.environ.get("MESH_TOKEN") or None
INSTANCE_ID = os.environ.get("INSTANCE_ID") or _default_instance_id()
INSTANCE_NAME = (
    os.environ.get("INSTANCE_NAME")
    or os.environ.get("NAME")
    or os.environ.get("USER")
    or "guest"
)
INSTANCE_PROJECT = os.environ.get("INSTANCE_PROJECT") or "default"

# Set by _recv_loop when the broker rejects us fatally (bad/rotated token or a
# refused registration). Carries the human-readable reason. When set, callers
# must NOT retry — the broker will reject every reconnect identically.
_FATAL_REASON: str | None = None


def _fmt(payload: dict) -> str:
    t = payload.get("type")
    if t == "message":
        sender = payload.get("from", "?")
        text = payload.get("text", "")
        to = payload.get("to", "")
        suffix = f" -> {to}" if to and to != INSTANCE_ID else ""
        return f"[{sender}{suffix}] {text}"
    if t == "register_ack":
        return f"[connected] id={payload.get('id') or INSTANCE_ID} peers={payload.get('peers') or []}"
    if t == "backlog":
        msgs = payload.get("messages", [])
        return f"[backlog] {len(msgs)} queued"
    if t == "auth_failed":
        return f"[auth-failed] {payload.get('reason', '')}"
    if t == "register_failed":
        return f"[register-failed] {payload.get('reason', 'registration rejected')}"
    if t == "instance_joined":
        i = payload.get("instance", {})
        return f"[joined] {i.get('id', '?')} ({i.get('name', '')})"
    if t == "instance_left":
        return f"[left] {payload.get('id', '?')}"
    return f"[{t or 'event'}] {json.dumps(payload, default=str)}"


def _build_register_frame() -> dict:
    frame = {
        "type": "register",
        "id": INSTANCE_ID,
        "name": INSTANCE_NAME,
        "project": INSTANCE_PROJECT,
    }
    if MESH_TOKEN:
        frame["token"] = MESH_TOKEN
    return frame


def _parse_line(line: str) -> dict | None:
    line = line.rstrip("\n")
    if not line:
        return None
    if line in ("/quit", "/exit"):
        raise KeyboardInterrupt
    if line.startswith("@"):
        parts = line[1:].split(" ", 1)
        if len(parts) == 2 and parts[1]:
            return {"type": "message", "to": parts[0], "text": parts[1]}
        return None
    return {"type": "broadcast", "text": line}


async def _recv_loop(ws):
    global _FATAL_REASON
    async for raw in ws:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        print(_fmt(payload), flush=True)
        t = payload.get("type")
        if t in ("auth_failed", "register_failed"):
            _FATAL_REASON = payload.get("reason") or t
            return


async def _stdin_loop(ws_holder):
    """Read stdin forever, sending each line over the currently-live ws.

    Created ONCE and persisted across reconnects (a run_in_executor readline
    can't be cancelled mid-read; recreating it per-reconnect would stack
    blocked reader threads). `ws_holder` is a one-element list whose [0] is the
    live websocket, or None while reconnecting. Returns only on EOF (Ctrl-D)
    or /quit — that's the sole clean-exit signal for interactive mode.
    """
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return  # EOF -> clean exit
        try:
            frame = _parse_line(line)
        except KeyboardInterrupt:
            return  # /quit -> clean exit
        if frame is None:
            continue
        ws = ws_holder[0]
        if ws is None:
            print("[not connected — message dropped]", flush=True)
            continue
        try:
            await ws.send(json.dumps(frame))
        except (websockets.ConnectionClosed, OSError):
            print("[send failed — reconnecting]", flush=True)


async def _interactive():
    backoff = 1.0
    ws_holder = [None]
    # The stdin reader lives across reconnects (see _stdin_loop docstring).
    stdin_task = asyncio.create_task(_stdin_loop(ws_holder))
    try:
        while True:
            try:
                async with websockets.connect(
                    BROKER_URL, ping_interval=20, ping_timeout=20
                ) as ws:
                    await ws.send(json.dumps(_build_register_frame()))
                    print(f"[connected] {INSTANCE_ID} -> {BROKER_URL}", flush=True)
                    backoff = 1.0
                    ws_holder[0] = ws
                    recv_task = asyncio.create_task(_recv_loop(ws))
                    done, _pending = await asyncio.wait(
                        {recv_task, stdin_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    ws_holder[0] = None
                    # Always retrieve recv_task's outcome so asyncio never logs
                    # "Task exception was never retrieved", and so a fatal
                    # rejection it observed is honored even if stdin also ended.
                    if recv_task not in done:
                        recv_task.cancel()
                    try:
                        await recv_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    if _FATAL_REASON is not None:
                        print(f"[fatal] {_FATAL_REASON} — not retrying.", flush=True)
                        sys.exit(1)
                    if stdin_task in done:
                        # EOF (Ctrl-D) or /quit with no fatal: clean exit.
                        return
                    # recv_task finished first => the connection dropped.
                    # Non-fatal drop: do NOT await the blocking stdin thread.
                    # Loop straight back into reconnect/backoff.
                    print("[disconnected — reconnecting…]", flush=True)
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                ws_holder[0] = None
                print(f"[disconnected] {e}; retry in {backoff:.1f}s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    finally:
        stdin_task.cancel()


async def _listen_only():
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(
                BROKER_URL, ping_interval=20, ping_timeout=20
            ) as ws:
                await ws.send(json.dumps(_build_register_frame()))
                print(f"[connected] {INSTANCE_ID} -> {BROKER_URL}", flush=True)
                backoff = 1.0
                await _recv_loop(ws)
            if _FATAL_REASON is not None:
                print(f"[fatal] {_FATAL_REASON} — not retrying.", flush=True)
                sys.exit(1)
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"[disconnected] {e}; retry in {backoff:.1f}s", flush=True)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)


async def _send_once(text: str, to: str | None):
    async with websockets.connect(BROKER_URL, ping_interval=None) as ws:
        await ws.send(json.dumps(_build_register_frame()))
        frame = {"type": "message", "to": to, "text": text} if to else {
            "type": "broadcast",
            "text": text,
        }
        # Send immediately after register (a fatal rejection closes the socket,
        # which surfaces here as ConnectionClosed -> treated as fatal below).
        try:
            await ws.send(json.dumps(frame))
        except websockets.ConnectionClosed:
            print("[fatal] registration rejected — message not sent.",
                  file=sys.stderr)
            sys.exit(1)
        # brief wait so the broker fans out before we close; inspect the reply
        # in case the broker reported a fatal rejection before closing.
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            try:
                resp = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                resp = {}
            if resp.get("type") in ("auth_failed", "register_failed"):
                print(_fmt(resp), flush=True)
                print("[fatal] registration rejected — message not sent.",
                      file=sys.stderr)
                sys.exit(1)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass


def _parse_args():
    p = argparse.ArgumentParser(description="Agent Mesh friend connector")
    p.add_argument("--listen", action="store_true", help="receive only, no stdin")
    p.add_argument("--send", metavar="TEXT", help="send one message and exit")
    p.add_argument("--to", metavar="INSTANCE_ID", default=None,
                   help="direct-message a specific instance (with --send)")
    return p.parse_args()


def main():
    if not BROKER_URL:
        print("error: BROKER_URL env var is required.", file=sys.stderr)
        print("ask the mesh host for their connect snippet.", file=sys.stderr)
        sys.exit(2)
    args = _parse_args()
    try:
        if args.send is not None:
            asyncio.run(_send_once(args.send, args.to))
        elif args.listen:
            asyncio.run(_listen_only())
        else:
            asyncio.run(_interactive())
    except KeyboardInterrupt:
        print("\n[bye]", file=sys.stderr)


if __name__ == "__main__":
    main()
