"""Agent Mesh — instance connect snippet.

Import this from a Claude Code REPL or run directly. Spawns a background
asyncio event loop in a thread so sync callers can fire-and-forget.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from typing import Optional

import websockets

# ---------------- defaults ----------------
INSTANCE_ID = "cc1"
NAME = "Claude 1"
PROJECT = "OPTFINDER"
BROKER_URL = "ws://localhost:8766"
# Optional shared-token auth. None or "" => no auth header sent.
MESH_TOKEN = os.environ.get("MESH_TOKEN") or None
# ------------------------------------------

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_ws_holder = {"ws": None, "connected": False}
_loop_started = threading.Event()
_stop_event: Optional[asyncio.Event] = None


def _start_loop():
    global _loop, _loop_thread, _stop_event

    def runner():
        global _loop, _stop_event
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _stop_event = asyncio.Event()
        _loop_started.set()
        _loop.create_task(_client_loop())
        _loop.run_forever()

    if _loop_thread is None or not _loop_thread.is_alive():
        _loop_thread = threading.Thread(target=runner, daemon=True, name="agent-mesh-loop")
        _loop_thread.start()
        _loop_started.wait(timeout=5)


def _fmt_incoming(payload: dict) -> str:
    t = payload.get("type")
    if t == "message":
        sender = payload.get("from", "?")
        to = payload.get("to", "")
        tag = "RELAY" if to and to != "you" and sender != "you" else ""
        suffix = f" ({tag})" if tag else ""
        return f"[INCOMING from {sender}{suffix}] {payload.get('text', '')}"
    if t == "memory_write":
        m = payload.get("memory", {})
        return f"[MEMORY] {m.get('key', '')} = {m.get('value', '')}  ({m.get('type', '')}, by {m.get('by', '?')})"
    if t == "memory_init":
        items = payload.get("memory", [])
        return f"[MEMORY INIT] {len(items)} entries"
    if t == "tasks_init":
        items = payload.get("tasks", [])
        return f"[TASKS INIT] {len(items)} open task(s) assigned to me"
    if t == "task_assigned":
        task = payload.get("task", {})
        return f"[TASK ASSIGNED] {task.get('id', '?')} \"{task.get('title', '')}\" (by {task.get('created_by', '?')})"
    if t == "task_completed":
        task = payload.get("task", {})
        return f"[TASK COMPLETED] {task.get('id', '?')} done by {task.get('done_by', '?')}: {task.get('result', '')}"
    if t == "backlog":
        msgs = payload.get("messages", [])
        return f"[BACKLOG] {len(msgs)} queued messages"
    if t == "approval_decision":
        verdict = "approved" if payload.get("decision") else "rejected"
        return f"[APPROVAL DECISION] {payload.get('id', '')} {verdict}: {payload.get('action', '')}"
    if t == "control":
        return f"[CONTROL] paused={payload.get('paused')}"
    return f"[{t or 'EVENT'}] {json.dumps(payload, default=str)}"


async def _client_loop():
    delay = 1.0
    while True:
        try:
            async with websockets.connect(BROKER_URL, ping_interval=20, ping_timeout=20) as ws:
                _ws_holder["ws"] = ws
                _ws_holder["connected"] = True
                # register
                reg_payload = {
                    "type": "register",
                    "id": INSTANCE_ID,
                    "name": NAME,
                    "project": PROJECT,
                }
                if MESH_TOKEN:
                    reg_payload["token"] = MESH_TOKEN
                await ws.send(json.dumps(reg_payload))
                print(f"[CONNECTED] {INSTANCE_ID} -> {BROKER_URL}")
                delay = 1.0
                async for raw in ws:
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        continue
                    if payload.get("type") == "auth_failed":
                        print(f"[AUTH FAILED] {payload.get('reason', '')} — check MESH_TOKEN")
                        return
                    if payload.get("type") == "backlog":
                        msgs = payload.get("messages", [])
                        print(f"[BACKLOG] {len(msgs)} queued messages")
                        for m in msgs:
                            print("  " + _fmt_incoming(m))
                    else:
                        print(_fmt_incoming(payload))
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"[DISCONNECTED] {e}; retry in {delay:.1f}s")
        except Exception as e:
            print(f"[ERROR] {e}; retry in {delay:.1f}s")
        finally:
            _ws_holder["ws"] = None
            _ws_holder["connected"] = False
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0)


async def _send_json(payload: dict):
    ws = _ws_holder.get("ws")
    if ws is None:
        print("[SKIP] not connected")
        return
    try:
        await ws.send(json.dumps(payload, default=str))
    except Exception as e:
        print(f"[SEND ERROR] {e}")


def _schedule(coro):
    _start_loop()
    if _loop is None:
        return None
    return asyncio.run_coroutine_threadsafe(coro, _loop)


# ---------------- public API ----------------
def broker_send(text: str, to: str = "you"):
    _schedule(_send_json({"type": "message", "to": to, "text": text}))


def broker_broadcast(text: str):
    _schedule(_send_json({"type": "broadcast", "text": text}))


def broker_status(task: str, workload: int = 0):
    _schedule(_send_json({"type": "status", "task": task, "workload": workload}))


def broker_approve_request(action: str, risk: str = "low", detail: str = ""):
    _schedule(_send_json({
        "type": "approval_request",
        "action": action,
        "risk": risk,
        "detail": detail,
    }))


def broker_memory(key: str, value, mem_type: str = "contract"):
    _schedule(_send_json({
        "type": "memory_write",
        "key": key,
        "value": value,
        "mem_type": mem_type,
    }))


def broker_typing(value: bool = True):
    _schedule(_send_json({"type": "typing", "value": bool(value)}))


def broker_task_create(title: str, assignee: str = "", priority: str = "normal",
                       deps: Optional[list] = None):
    """Create a task. If `assignee` is another instance id, they get task_assigned."""
    _schedule(_send_json({
        "type": "task_create",
        "title": title,
        "assignee": assignee,
        "priority": priority,
        "deps": list(deps or []),
    }))


def broker_task_claim(task_id: str):
    _schedule(_send_json({"type": "task_claim", "id": task_id}))


def broker_task_status(task_id: str, status: str):
    _schedule(_send_json({"type": "task_status", "id": task_id, "status": status}))


def broker_task_done(task_id: str, result: str = ""):
    _schedule(_send_json({"type": "task_done", "id": task_id, "result": result}))


# Start the loop on import
_start_loop()


# ---------------- CLI ----------------
def _interactive():
    print(f"Agent Mesh connect — id={INSTANCE_ID} name={NAME} project={PROJECT}")
    print("Commands: send <to> <text...> | broadcast <text...> | status <task...> [|<workload>] | quit")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        parts = line.split(" ", 2)
        cmd = parts[0].lower()
        if cmd == "send" and len(parts) >= 3:
            broker_send(parts[2], to=parts[1])
        elif cmd == "broadcast" and len(parts) >= 2:
            text = line[len("broadcast"):].strip()
            broker_broadcast(text)
        elif cmd == "status" and len(parts) >= 2:
            payload = line[len("status"):].strip()
            workload = 0
            if "|" in payload:
                payload, w = payload.rsplit("|", 1)
                try:
                    workload = int(w.strip())
                except Exception:
                    workload = 0
            broker_status(payload.strip(), workload=workload)
        else:
            print("Unknown command")


if __name__ == "__main__":
    # ensure loop is up
    _start_loop()
    time.sleep(0.5)
    _interactive()
