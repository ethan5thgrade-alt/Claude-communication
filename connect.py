"""Agent Mesh — instance connect snippet.

Import this from a Claude Code REPL or run directly. Spawns a background
asyncio event loop in a thread so sync callers can fire-and-forget.
"""
from __future__ import annotations

import asyncio
import json
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
# ------------------------------------------

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_ws_holder = {"ws": None, "connected": False}
_loop_started = threading.Event()
_stop_event: Optional[asyncio.Event] = None

# approval correlation: ap_id -> {"event": threading.Event, "decision": bool|None}
_pending_approvals: dict = {}
# queue of waiters that haven't yet learned their ap_id (FIFO matching to approval_pending)
_pending_approval_waiters: list = []
_approval_lock = threading.Lock()

# vote-wait tracking: vote_id -> {"event": threading.Event, "winner": str|None}
_pending_votes: dict = {}
# stash for the most recently issued vote_create awaiting its server-assigned id
_pending_vote_creates: list = []
_vote_lock = threading.Lock()


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
    if t == "approval_pending":
        return f"[APPROVAL PENDING] id={payload.get('id', '')} action={payload.get('action', '')}"
    if t == "approval_decision":
        verdict = "approved" if payload.get("decision") else "rejected"
        return f"[APPROVAL DECISION] {payload.get('id', '')} {verdict}: {payload.get('action', '')}"
    if t == "vote_pending":
        return f"[VOTE PENDING] {payload.get('vote_id', '')} q={payload.get('question', '')}"
    if t == "vote_open":
        v = payload.get("vote", {})
        return f"[VOTE OPEN] {v.get('id', '')} q={v.get('question', '')} opts={v.get('options', [])}"
    if t == "vote_resolved":
        return f"[VOTE RESOLVED] {payload.get('vote_id', '')} winner={payload.get('winner', '')}"
    if t == "control":
        return f"[CONTROL] paused={payload.get('paused')}"
    return f"[{t or 'EVENT'}] {json.dumps(payload, default=str)}"


def _handle_approval_pending(payload: dict):
    ap_id = payload.get("id")
    if not ap_id:
        return
    with _approval_lock:
        # claim the oldest queued waiter and bind it to this ap_id
        if _pending_approval_waiters:
            slot = _pending_approval_waiters.pop(0)
            slot["ap_id"] = ap_id
            _pending_approvals[ap_id] = slot


def _handle_approval_decision(payload: dict):
    ap_id = payload.get("id")
    if not ap_id:
        return
    with _approval_lock:
        slot = _pending_approvals.pop(ap_id, None)
    if slot is None:
        return
    slot["decision"] = bool(payload.get("decision"))
    slot["event"].set()


async def _client_loop():
    delay = 1.0
    while True:
        try:
            async with websockets.connect(BROKER_URL, ping_interval=20, ping_timeout=20) as ws:
                _ws_holder["ws"] = ws
                _ws_holder["connected"] = True
                # register
                await ws.send(json.dumps({
                    "type": "register",
                    "id": INSTANCE_ID,
                    "name": NAME,
                    "project": PROJECT,
                }))
                print(f"[CONNECTED] {INSTANCE_ID} -> {BROKER_URL}")
                delay = 1.0
                async for raw in ws:
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        continue
                    ptype = payload.get("type")
                    if ptype == "approval_pending":
                        _handle_approval_pending(payload)
                        print(_fmt_incoming(payload))
                        continue
                    if ptype == "approval_decision":
                        _handle_approval_decision(payload)
                        print(_fmt_incoming(payload))
                        continue
                    # vote events: handle then keep going (they should also print)
                    _handle_vote_event(payload)
                    if ptype == "backlog":
                        msgs = payload.get("messages", [])
                        print(f"[BACKLOG] {len(msgs)} queued messages")
                        for m in msgs:
                            mt = m.get("type")
                            if mt == "approval_pending":
                                _handle_approval_pending(m)
                            elif mt == "approval_decision":
                                _handle_approval_decision(m)
                            else:
                                _handle_vote_event(m)
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


def broker_approve_and_wait(action: str, risk: str = "low", detail: str = "",
                            timeout: float = 300.0) -> Optional[bool]:
    """Send an approval_request and block (sync) until the broker returns a decision.

    Returns True if approved, False if rejected, None on timeout.
    """
    slot = {"event": threading.Event(), "decision": None, "ap_id": None}
    with _approval_lock:
        _pending_approval_waiters.append(slot)
    fut = _schedule(_send_json({
        "type": "approval_request",
        "action": action,
        "risk": risk,
        "detail": detail,
    }))
    # ensure the send actually went out before we wait on a decision
    if fut is not None:
        try:
            fut.result(timeout=5)
        except Exception:
            pass
    ok = slot["event"].wait(timeout=timeout)
    if not ok:
        # cleanup: drop this slot from the wait queues
        with _approval_lock:
            if slot in _pending_approval_waiters:
                _pending_approval_waiters.remove(slot)
            if slot.get("ap_id") and _pending_approvals.get(slot["ap_id"]) is slot:
                _pending_approvals.pop(slot["ap_id"], None)
        return None
    return slot["decision"]


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


# ---------------- votes ----------------
def _handle_vote_event(payload: dict):
    """Inspect an incoming payload and update the vote-wait registry.

    - On `vote_pending`: hand the server-assigned vote_id to the most recent
      caller of broker_vote_and_wait (FIFO of pending creates).
    - On `vote_resolved`: set the event so a waiter unblocks.
    """
    t = payload.get("type")
    if t == "vote_pending":
        vid = payload.get("vote_id")
        if not vid:
            return
        with _vote_lock:
            if _pending_vote_creates:
                slot = _pending_vote_creates.pop(0)
                slot["vote_id"] = vid
                _pending_votes[vid] = slot
                slot["ready_event"].set()
    elif t == "vote_resolved":
        vid = payload.get("vote_id")
        winner = payload.get("winner")
        if not vid:
            return
        with _vote_lock:
            slot = _pending_votes.get(vid)
            if slot is not None:
                slot["winner"] = winner
                slot["event"].set()


def broker_vote_create(question: str, options: list, threshold: Optional[int] = None):
    """Create a vote. Fire-and-forget."""
    _schedule(_send_json({
        "type": "vote_create",
        "question": question,
        "options": list(options),
        "threshold": threshold,
    }))


def broker_vote_cast(vote_id: str, option: str):
    """Cast a ballot. Fire-and-forget."""
    _schedule(_send_json({
        "type": "vote_cast",
        "vote_id": vote_id,
        "option": option,
    }))


def broker_vote_and_wait(question: str, options: list, threshold: Optional[int] = None,
                         timeout: float = 300.0) -> Optional[str]:
    """Create a vote and block until it resolves. Returns the winning option (str)
    or None on timeout."""
    slot = {
        "ready_event": threading.Event(),  # set when vote_pending arrives w/ id
        "event": threading.Event(),         # set when vote_resolved arrives
        "vote_id": None,
        "winner": None,
    }
    with _vote_lock:
        _pending_vote_creates.append(slot)
    _schedule(_send_json({
        "type": "vote_create",
        "question": question,
        "options": list(options),
        "threshold": threshold,
    }))
    # wait briefly for the broker to echo back the assigned id
    if not slot["ready_event"].wait(timeout=min(10.0, timeout)):
        with _vote_lock:
            try:
                _pending_vote_creates.remove(slot)
            except ValueError:
                pass
        return None
    # now wait for resolution
    if not slot["event"].wait(timeout=timeout):
        with _vote_lock:
            _pending_votes.pop(slot.get("vote_id"), None)
        return None
    with _vote_lock:
        _pending_votes.pop(slot.get("vote_id"), None)
    return slot["winner"]


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
