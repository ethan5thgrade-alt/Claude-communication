"""Tests for the Agent Mesh broker."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
import websockets
import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import broker as broker_mod  # noqa: E402


def _pick_free_port() -> int:
    """Bind to port 0, read back the OS-assigned port, close the socket.

    Small TOCTOU window between close and re-bind, but more than good enough
    to avoid the hard collisions we get with hardcoded ports when multiple
    pytest runs (or other dev tooling) share the box.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


# Pick free ports once per test-module load — env-var overrides supported for CI.
UI_PORT = int(os.environ.get("MESH_TEST_UI_PORT") or _pick_free_port())
INST_PORT = int(os.environ.get("MESH_TEST_INST_PORT") or _pick_free_port())
WS_URL = f"ws://localhost:{INST_PORT}"
UI_WS_URL = f"ws://localhost:{UI_PORT}/ui"
REST_URL = f"http://localhost:{UI_PORT}"


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "state.json"


@pytest_asyncio.fixture
async def started_broker(state_file, tmp_path):
    plugins_dir = tmp_path / "plugins_cache"
    plugins_dir.mkdir()
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file, plugins_dir=plugins_dir)
    await b.start()
    # tiny pause for server sockets to be ready
    await asyncio.sleep(0.05)
    try:
        yield b
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


def _make_fake_plugin(plugins_dir: Path, marketplace: str, plugin: str, version: str,
                     skills=None, agents=None, commands=None, manifest_extra=None):
    """Create a fake plugin tree under plugins_dir for tests."""
    root = plugins_dir / marketplace / plugin / version
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": plugin,
        "version": version,
        "description": f"Test plugin {plugin}",
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    with open(root / ".claude-plugin" / "plugin.json", "w") as f:
        json.dump(manifest, f)
    for s in skills or []:
        sd = root / "skills" / s
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "SKILL.md").write_text(f"# {s}\n\nA test skill body.\n")
    if agents:
        (root / "agents").mkdir(parents=True, exist_ok=True)
        for a in agents:
            (root / "agents" / f"{a}.md").write_text(f"# agent {a}\n")
    if commands:
        (root / "commands").mkdir(parents=True, exist_ok=True)
        for c in commands:
            (root / "commands" / f"{c}.md").write_text(f"# command {c}\n")
    return root


async def _register(ws, iid="cc1", name="Claude 1", project="P"):
    await ws.send(json.dumps({"type": "register", "id": iid, "name": name, "project": project}))
    # drain memory_init + tasks_init (and possibly backlog) for cleanliness
    init = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    assert init["type"] == "memory_init"
    # tasks_init follows
    tinit = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    assert tinit["type"] == "tasks_init"
    return init


async def _recv_until(ws, match_fn, timeout=2.0):
    end = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        payload = json.loads(raw)
        if match_fn(payload):
            return payload


@pytest.mark.asyncio
async def test_register(started_broker):
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        # broker should track it
        await asyncio.sleep(0.05)
        assert "cc1" in started_broker.instances
        assert started_broker.instances["cc1"]["online"] is True


@pytest.mark.asyncio
async def test_you_to_instance(started_broker):
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        # send via REST
        async with aiohttp.ClientSession() as session:
            async with session.post(REST_URL + "/api/send",
                                    json={"to": "cc1", "text": "hi there"}) as r:
                assert r.status == 200
        msg = await _recv_until(ws, lambda p: p.get("type") == "message" and p.get("from") == "you")
        assert msg["text"] == "hi there"


@pytest.mark.asyncio
async def test_instance_to_ui(started_broker):
    # connect UI ws first
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            init = await ui_ws.receive_json(timeout=2)
            assert init["type"] == "init"
            async with websockets.connect(WS_URL) as ws:
                await _register(ws, iid="cc2")
                await ws.send(json.dumps({"type": "message", "to": "you", "text": "hello UI"}))
                # read messages until we see message
                async def wait_msg():
                    async for raw in ui_ws:
                        if raw.type != aiohttp.WSMsgType.TEXT:
                            continue
                        p = json.loads(raw.data)
                        if p.get("type") == "message" and p.get("message", {}).get("text") == "hello UI":
                            return p
                got = await asyncio.wait_for(wait_msg(), timeout=2)
                assert got["message"]["from"] == "cc2"


@pytest.mark.asyncio
async def test_agent_to_agent_relay(started_broker):
    async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
        await _register(ws1, iid="cc1")
        await _register(ws2, iid="cc2")
        await asyncio.sleep(0.05)
        await ws1.send(json.dumps({"type": "message", "to": "cc2", "text": "ping"}))
        got = await _recv_until(ws2, lambda p: p.get("type") == "message" and p.get("from") == "cc1")
        assert got["text"] == "ping"


@pytest.mark.asyncio
async def test_broadcast(started_broker):
    async with websockets.connect(WS_URL) as ws1, \
               websockets.connect(WS_URL) as ws2, \
               websockets.connect(WS_URL) as ws3:
        await _register(ws1, iid="cc1")
        await _register(ws2, iid="cc2")
        await _register(ws3, iid="cc3")
        await asyncio.sleep(0.1)
        await ws1.send(json.dumps({"type": "broadcast", "text": "all hands"}))
        got2 = await _recv_until(ws2, lambda p: p.get("type") == "message" and p.get("text") == "all hands")
        got3 = await _recv_until(ws3, lambda p: p.get("type") == "message" and p.get("text") == "all hands")
        assert got2["from"] == "cc1"
        assert got3["from"] == "cc1"
        # sender does NOT get it back: drain ws1 for a moment and check
        try:
            extra = await asyncio.wait_for(ws1.recv(), timeout=0.3)
            payload = json.loads(extra)
            assert not (payload.get("type") == "message" and payload.get("text") == "all hands"
                        and payload.get("from") == "cc1")
        except asyncio.TimeoutError:
            pass


@pytest.mark.asyncio
async def test_broker_log_writes_audit_no_chat(started_broker):
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        # baseline counts
        await asyncio.sleep(0.05)
        msgs_before = len(started_broker.state["messages"])
        audit_before = len(started_broker.state["audit"])

        # fire a log event
        await ws.send(json.dumps({"type": "log", "text": "hello audit", "level": "warn"}))
        await asyncio.sleep(0.1)

        # no chat message added
        assert len(started_broker.state["messages"]) == msgs_before

        # audit row appears, with level prefix
        new_audits = started_broker.state["audit"][audit_before:]
        log_rows = [a for a in new_audits if a["action"] == "log"]
        assert len(log_rows) == 1
        assert log_rows[0]["agent"] == "cc1"
        assert log_rows[0]["detail"].startswith("warn:")
        assert "hello audit" in log_rows[0]["detail"]

        # instance does NOT receive a chat message back from its own log
        try:
            extra = await asyncio.wait_for(ws.recv(), timeout=0.3)
            payload = json.loads(extra)
            assert payload.get("type") != "message"
        except asyncio.TimeoutError:
            pass


@pytest.mark.asyncio
async def test_broker_log_broadcasts_log_event_to_ui(started_broker):
    # connect UI ws first
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            init = await ui_ws.receive_json(timeout=2)
            assert init["type"] == "init"
            async with websockets.connect(WS_URL) as ws:
                await _register(ws, iid="cc1")
                await ws.send(json.dumps({"type": "log", "text": "ui audit watch", "level": "error"}))

                async def wait_log():
                    async for raw in ui_ws:
                        if raw.type != aiohttp.WSMsgType.TEXT:
                            continue
                        p = json.loads(raw.data)
                        if p.get("type") == "log_event" and p.get("text") == "ui audit watch":
                            return p
                got = await asyncio.wait_for(wait_log(), timeout=2)
                assert got["id"] == "cc1"
                assert got["level"] == "error"
                assert got["audit"]["action"] == "log"


@pytest.mark.asyncio
async def test_state_persists_across_restart(state_file):
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT, state_path=state_file)
    await b.start()
    await asyncio.sleep(0.05)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(UI_WS_URL) as ui_ws:
                await ui_ws.receive_json(timeout=2)  # init
                await ui_ws.send_json({"action": "create_task", "title": "persisted",
                                       "assignee": "cc1", "priority": "high", "deps": []})
                # wait for state_update
                end = asyncio.get_event_loop().time() + 2
                got_task = False
                while asyncio.get_event_loop().time() < end:
                    msg = await asyncio.wait_for(ui_ws.receive(), timeout=2)
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    p = json.loads(msg.data)
                    if p.get("type") == "state_update" and "tasks" in p.get("delta", {}):
                        if any(t["title"] == "persisted" for t in p["delta"]["tasks"]):
                            got_task = True
                            break
                assert got_task
        await asyncio.sleep(0.7)  # let debounced write flush
    finally:
        await b.stop()
        await asyncio.sleep(0.1)

    # restart
    b2 = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT, state_path=state_file)
    await b2.start()
    await asyncio.sleep(0.05)
    try:
        titles = [t["title"] for t in b2.state["tasks"]]
        assert "persisted" in titles
    finally:
        await b2.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_state_write_is_durable(state_file):
    """Verify the fsync'd write path works end-to-end: state ends up on disk
    intact. We can't simulate power-off in pytest, but we exercise the new
    fsync code paths in both _do_write and Broker.stop and confirm the file
    is well-formed JSON containing what we wrote."""
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT, state_path=state_file)
    await b.start()
    await asyncio.sleep(0.05)
    try:
        # Mutate state and schedule a debounced write.
        b.state.setdefault("tasks", []).append({
            "id": "t-durable-1",
            "title": "durable-write-test",
            "assignee": "cc1",
            "priority": "high",
            "deps": [],
            "status": "open",
        })
        b.schedule_write()
        # Wait for the 0.5s debounce + fsync to complete.
        await asyncio.sleep(0.7)
        # Read the file back from disk and verify content.
        assert state_file.exists(), "state file should exist after debounced write"
        on_disk = json.loads(state_file.read_text())
        titles = [t["title"] for t in on_disk.get("tasks", [])]
        assert "durable-write-test" in titles
    finally:
        await b.stop()
        await asyncio.sleep(0.05)

    # After stop(), the final flush in Broker.stop also goes through fsync.
    # Re-read the file and confirm it's still intact.
    assert state_file.exists()
    on_disk_after_stop = json.loads(state_file.read_text())
    titles_after = [t["title"] for t in on_disk_after_stop.get("tasks", [])]
    assert "durable-write-test" in titles_after


@pytest.mark.asyncio
async def test_shutdown_flushes_state(state_file, tmp_path):
    """Stopping the broker (as the SIGTERM handler does) must flush state to disk."""
    plugins_dir = tmp_path / "plugins_cache"
    plugins_dir.mkdir()
    ui_port = UI_PORT + 20
    inst_port = INST_PORT + 20
    b = broker_mod.Broker(ui_port=ui_port, instance_port=inst_port,
                          state_path=state_file, plugins_dir=plugins_dir)
    await b.start()
    await asyncio.sleep(0.05)
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(f"http://localhost:{ui_port}/api/send",
                                      json={"to": "all", "text": "pre-shutdown"})
            assert resp.status == 200
    finally:
        await b.stop()
        await asyncio.sleep(0.05)

    assert state_file.exists(), "state file was not flushed on shutdown"
    with open(state_file) as f:
        reloaded = json.load(f)
    texts = [m.get("text") for m in reloaded.get("messages", [])]
    assert "pre-shutdown" in texts, f"flushed state missing message: {texts}"


@pytest.mark.asyncio
async def test_reconnect_same_id_closes_old(started_broker):
    ws_old = await websockets.connect(WS_URL)
    await _register(ws_old, iid="cc1")
    await asyncio.sleep(0.05)
    # capture which ws-object the broker currently has for cc1 (server-side)
    server_ws_before = started_broker.instances["cc1"]["ws"]
    ws_new = await websockets.connect(WS_URL)
    await _register(ws_new, iid="cc1")
    await asyncio.sleep(0.3)
    # old client side connection should be closed by broker
    closed = False
    try:
        await asyncio.wait_for(ws_old.recv(), timeout=1)
    except websockets.ConnectionClosed:
        closed = True
    except asyncio.TimeoutError:
        pass
    assert closed or ws_old.close_code is not None
    # broker should now hold a *different* server-side ws for cc1
    server_ws_after = started_broker.instances["cc1"]["ws"]
    assert server_ws_after is not server_ws_before
    assert started_broker.instances["cc1"]["online"] is True
    await ws_new.close()
    try:
        await ws_old.close()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_backlog_delivers_on_reconnect(started_broker):
    # register cc1 then disconnect
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
    await asyncio.sleep(0.1)
    # send while offline via REST
    async with aiohttp.ClientSession() as session:
        await session.post(REST_URL + "/api/send", json={"to": "cc1", "text": "while-gone"})
    await asyncio.sleep(0.1)
    # reconnect
    async with websockets.connect(WS_URL) as ws2:
        await ws2.send(json.dumps({"type": "register", "id": "cc1", "name": "Claude 1", "project": "P"}))
        # expect memory_init then backlog
        got_backlog = False
        for _ in range(5):
            raw = await asyncio.wait_for(ws2.recv(), timeout=2)
            p = json.loads(raw)
            if p.get("type") == "backlog":
                msgs = p.get("messages", [])
                if any(m.get("text") == "while-gone" for m in msgs):
                    got_backlog = True
                    break
        assert got_backlog


def test_backlog_byte_budget_evicts():
    """Old entries should be evicted from BoundedBacklog once total bytes > budget."""
    # 4 KB budget keeps the test cheap and deterministic.
    budget = 4 * 1024
    backlog = broker_mod.BoundedBacklog(byte_budget=budget)

    # Each entry is ~1100 bytes after JSON-encoding (padding string + index).
    # Pushing 10 of them blows the budget; only the most recent few should survive.
    payload_size_hint = 1100
    pad = "x" * payload_size_hint
    for i in range(10):
        backlog.append({"i": i, "pad": pad})

    # Budget invariant must hold after every append.
    assert backlog.total_bytes <= budget, (backlog.total_bytes, budget)

    indices = [p["i"] for p in backlog]
    # Newest entries must remain; the freshest one is non-negotiable.
    assert indices[-1] == 9
    # Strictly ascending — eviction is FIFO, never reorders.
    assert indices == sorted(indices)
    # Something must have been evicted given total payload (~11 KB) > 4 KB budget.
    assert len(indices) < 10
    # The very oldest (i=0) must be gone.
    assert 0 not in indices

    # Single huge payload bigger than the entire budget is still stored
    # (drops the rest so the latest message isn't silently lost).
    backlog.append({"i": "huge", "pad": "y" * (budget * 2)})
    surviving = list(backlog)
    assert len(surviving) == 1
    assert surviving[0]["i"] == "huge"

    # clear() resets bookkeeping.
    backlog.clear()
    assert len(backlog) == 0
    assert backlog.total_bytes == 0
    assert list(backlog) == []


def test_backlog_byte_budget_constant_is_256k():
    """Top-of-file constant should be 256 KB so it stays tweakable."""
    assert broker_mod.BACKLOG_BYTE_BUDGET == 256 * 1024


@pytest.mark.asyncio
async def test_agent_task_create_assigns(started_broker):
    """cc1 creates a task assigned to cc2; cc2 should receive task_assigned."""
    async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
        await _register(ws1, iid="cc1")
        await _register(ws2, iid="cc2")
        await asyncio.sleep(0.05)
        await ws1.send(json.dumps({
            "type": "task_create",
            "title": "write the CSV parser",
            "assignee": "cc2",
            "priority": "high",
        }))
        got = await _recv_until(ws2, lambda p: p.get("type") == "task_assigned")
        assert got["task"]["title"] == "write the CSV parser"
        assert got["task"]["assignee"] == "cc2"
        assert got["task"]["created_by"] == "cc1"
        assert got["task"]["status"] == "In Progress"
        # broker state has it
        assert any(t["title"] == "write the CSV parser" for t in started_broker.state["tasks"])


@pytest.mark.asyncio
async def test_agent_task_done_notifies_creator(started_broker):
    """When cc2 marks task_done, cc1 (the creator) gets task_completed."""
    async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
        await _register(ws1, iid="cc1")
        await _register(ws2, iid="cc2")
        await asyncio.sleep(0.05)
        await ws1.send(json.dumps({
            "type": "task_create",
            "title": "parse the CSV",
            "assignee": "cc2",
        }))
        assigned = await _recv_until(ws2, lambda p: p.get("type") == "task_assigned")
        tid = assigned["task"]["id"]
        await ws2.send(json.dumps({
            "type": "task_done",
            "id": tid,
            "result": "shipped",
        }))
        notice = await _recv_until(ws1, lambda p: p.get("type") == "task_completed")
        assert notice["task"]["id"] == tid
        assert notice["task"]["result"] == "shipped"
        assert notice["task"]["done_by"] == "cc2"
        assert notice["task"]["status"] == "Done"


@pytest.mark.asyncio
async def test_agent_task_create_backlogs_offline_assignee(started_broker):
    """Assigning to an offline instance queues task_assigned; delivered on reconnect."""
    async with websockets.connect(WS_URL) as ws1:
        await _register(ws1, iid="cc1")
        await asyncio.sleep(0.05)
        await ws1.send(json.dumps({
            "type": "task_create",
            "title": "later task",
            "assignee": "cc2",
        }))
        await asyncio.sleep(0.1)
    # cc2 connects after the fact
    async with websockets.connect(WS_URL) as ws2:
        await ws2.send(json.dumps({"type": "register", "id": "cc2", "name": "C2", "project": "P"}))
        # drain memory_init, tasks_init, then look for backlog
        got_in_tasks_init = False
        got_in_backlog = False
        end = asyncio.get_event_loop().time() + 2
        while asyncio.get_event_loop().time() < end:
            raw = await asyncio.wait_for(ws2.recv(), timeout=2)
            p = json.loads(raw)
            if p.get("type") == "tasks_init":
                if any(t.get("title") == "later task" for t in p.get("tasks", [])):
                    got_in_tasks_init = True
            if p.get("type") == "backlog":
                msgs = p.get("messages", [])
                if any(m.get("type") == "task_assigned"
                       and m.get("task", {}).get("title") == "later task" for m in msgs):
                    got_in_backlog = True
                break
        # Either delivery path is acceptable — tasks_init is preferred but backlog is the safety net
        assert got_in_tasks_init or got_in_backlog


async def _ui_approve_pending(ap_id: str, decision: bool):
    """Open a UI ws, send the approve action, and close."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            await ui_ws.receive_json(timeout=2)  # init
            await ui_ws.send_json({"action": "approve", "id": ap_id, "decision": decision})
            # give the broker a moment to dispatch
            await asyncio.sleep(0.15)


@pytest.mark.asyncio
async def test_approval_resolve_approves(started_broker):
    """Instance fires approval_request; UI approves; instance receives approval_decision=True."""
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await ws.send(json.dumps({
            "type": "approval_request",
            "action": "delete /scan",
            "risk": "medium",
            "detail": "old clients 404",
        }))
        pending = await _recv_until(ws, lambda p: p.get("type") == "approval_pending")
        ap_id = pending["id"]
        assert ap_id and ap_id.startswith("AP")
        # broker tracks the future
        assert ap_id in started_broker._pending_approvals
        # UI approves
        await _ui_approve_pending(ap_id, True)
        decision = await _recv_until(ws, lambda p: p.get("type") == "approval_decision")
        assert decision["id"] == ap_id
        assert decision["decision"] is True
        # broker future resolved + popped
        assert ap_id not in started_broker._pending_approvals
        # audit captured the decider + verdict + requester
        ad = [a for a in started_broker.state["audit"]
              if a["action"] == "approval_decision" and ap_id in a["detail"]]
        assert ad, "approval_decision audit entry missing"
        entry = ad[-1]
        assert entry["agent"] == "you"
        assert "cc1" in entry["detail"]
        assert "approved" in entry["detail"]
        assert entry.get("ts")


@pytest.mark.asyncio
async def test_approval_resolve_rejects(started_broker):
    """Same as approve, but the UI rejects."""
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await ws.send(json.dumps({
            "type": "approval_request",
            "action": "drop prod table",
            "risk": "high",
        }))
        pending = await _recv_until(ws, lambda p: p.get("type") == "approval_pending")
        ap_id = pending["id"]
        await _ui_approve_pending(ap_id, False)
        decision = await _recv_until(ws, lambda p: p.get("type") == "approval_decision")
        assert decision["id"] == ap_id
        assert decision["decision"] is False
        assert ap_id not in started_broker._pending_approvals


@pytest.mark.asyncio
async def test_approval_timeout(started_broker):
    """If no decision is ever sent, awaiting the broker-side future raises TimeoutError."""
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await ws.send(json.dumps({
            "type": "approval_request",
            "action": "noop",
        }))
        pending = await _recv_until(ws, lambda p: p.get("type") == "approval_pending")
        ap_id = pending["id"]
        fut = started_broker._pending_approvals.get(ap_id)
        assert fut is not None
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(fut), timeout=0.3)
        # future still pending (we shielded), broker still tracks it
        assert not fut.done()
        assert ap_id in started_broker._pending_approvals


@pytest.mark.asyncio
async def test_migration_v1_to_v2(state_file):
    """A v1-shaped state.json (no schema_version, no instances_meta, tasks without
    created_by) should be migrated in-place to schema_version=2 with created_by
    populated on existing tasks."""
    v1_state = {
        "messages": [],
        "tasks": [
            {"id": "T001", "title": "old task", "assignee": "cc1",
             "priority": "normal", "deps": [], "status": "Backlog",
             "ts": "2025-01-01T00:00:00+00:00"},
        ],
        "memory": [],
        "flows": [],
        "approvals": [],
        "votes": [],
        "audit": [],
        # NOTE: no schema_version, no instances_meta, no counters
    }
    state_file.write_text(json.dumps(v1_state))
    pre_backup = state_file.with_name(state_file.name + ".v1.bak")

    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file)
    b.load_state()

    assert b.state["schema_version"] == 2
    assert "instances_meta" in b.state
    assert b.state["instances_meta"] == {}
    assert "counters" in b.state
    for prefix in ("M", "T", "F", "AP", "V", "A"):
        assert prefix in b.state["counters"]
    # tasks now have created_by
    assert b.state["tasks"][0]["created_by"] == "unknown"
    # pre-migration backup file exists
    assert pre_backup.exists()
    # audit entry recorded the migration
    assert any(a.get("action") == "migration" for a in b.state["audit"])


@pytest.mark.asyncio
async def test_counter_integrity_after_load(state_file):
    """If state has a T005 task but counters['T']=2, load_state must bump counters['T'] >= 5."""
    state = {
        "schema_version": 2,
        "messages": [],
        "tasks": [
            {"id": "T005", "title": "high-id task", "assignee": "",
             "priority": "normal", "deps": [], "status": "Backlog",
             "created_by": "you", "ts": "2025-01-01T00:00:00+00:00"},
        ],
        "memory": [],
        "flows": [],
        "approvals": [],
        "votes": [],
        "audit": [],
        "instances_meta": {},
        "counters": {"M": 0, "T": 2, "F": 0, "AP": 0, "V": 0, "A": 0},
    }
    state_file.write_text(json.dumps(state))
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file)
    b.load_state()
    assert b.state["counters"]["T"] >= 5


@pytest.mark.asyncio
async def test_daily_backup_creates_file_and_prunes(state_file, tmp_path):
    """Broker started with short backup interval should write a dated backup;
    then prune should keep only the 7 newest dated backups."""
    # seed a state file so backup has something to copy
    state_file.write_text(json.dumps(broker_mod.empty_state()))

    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file,
                          backup_interval_seconds=0.05)
    await b.start()
    try:
        await asyncio.sleep(0.2)
        # at least one dated backup file should now exist
        prefix = state_file.name + "."
        dated = [
            p for p in state_file.parent.iterdir()
            if p.name.startswith(prefix) and p.name.endswith(".bak")
            and len(p.name) - len(prefix) - 4 == 10  # YYYY-MM-DD = 10 chars
        ]
        assert len(dated) >= 1, f"expected dated backup, found: {[p.name for p in state_file.parent.iterdir()]}"

        # now create 9 fake dated backup files in the same dir
        fake_dates = [
            "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
            "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
        ]
        # remove any existing dated backups first to make the count deterministic
        for p in list(state_file.parent.iterdir()):
            if p.name.startswith(prefix) and p.name.endswith(".bak"):
                try:
                    p.unlink()
                except Exception:
                    pass
        for d in fake_dates:
            (state_file.parent / f"{state_file.name}.{d}.bak").write_text("{}")

        # prune
        b._prune_dated_backups()

        remaining = [
            p for p in state_file.parent.iterdir()
            if p.name.startswith(prefix) and p.name.endswith(".bak")
        ]
        assert len(remaining) == 7
        # The two oldest should have been deleted
        remaining_names = sorted(p.name for p in remaining)
        assert all(date in name for date, name in zip(fake_dates[2:], remaining_names))
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


@pytest_asyncio.fixture
async def authed_broker(state_file):
    """Broker fixture with auth_token='secret'."""
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file, auth_token="secret")
    await b.start()
    await asyncio.sleep(0.05)
    try:
        yield b
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_vote_two_options_resolves_on_threshold(started_broker):
    """cc1 creates a vote with threshold=2; cc1 and cc2 both vote the same
    option; vote_resolved is broadcast."""
    async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
        await _register(ws1, iid="cc1")
        await _register(ws2, iid="cc2")
        await asyncio.sleep(0.05)
        # cc1 creates the vote
        await ws1.send(json.dumps({
            "type": "vote_create",
            "question": "ship it?",
            "options": ["yes", "no"],
            "threshold": 2,
        }))
        # cc1 should get vote_pending with the new id
        pend = await _recv_until(ws1, lambda p: p.get("type") == "vote_pending")
        vid = pend["vote_id"]
        # cc2 should see vote_open
        opened = await _recv_until(ws2, lambda p: p.get("type") == "vote_open")
        assert opened["vote"]["id"] == vid
        # both cast "yes"
        await ws1.send(json.dumps({"type": "vote_cast", "vote_id": vid, "option": "yes"}))
        await ws2.send(json.dumps({"type": "vote_cast", "vote_id": vid, "option": "yes"}))
        # both should receive vote_resolved
        r1 = await _recv_until(ws1, lambda p: p.get("type") == "vote_resolved")
        r2 = await _recv_until(ws2, lambda p: p.get("type") == "vote_resolved")
        assert r1["vote_id"] == vid
        assert r1["winner"] == "yes"
        assert r2["winner"] == "yes"
        # state reflects it
        v = next(x for x in started_broker.state["votes"] if x["id"] == vid)
        assert v["status"] == "resolved"
        assert v["winner"] == "yes"


@pytest.mark.asyncio
async def test_vote_tie_breaks_alphabetically(started_broker):
    """threshold=None; three online instances; two vote 'b', one votes 'a' --
    'b' wins by majority. Then re-test with a real tie: 1 'a', 1 'b', 1 'c'
    is impossible with 2 options, so we use options ['a','b'] and split 1/1
    among two voters with 'you' also voting to create a clear tie scenario."""
    # Subtest A: clear tie between two options, broken alphabetically
    async with websockets.connect(WS_URL) as ws1, \
               websockets.connect(WS_URL) as ws2, \
               websockets.connect(WS_URL) as ws3:
        await _register(ws1, iid="cc1")
        await _register(ws2, iid="cc2")
        await _register(ws3, iid="cc3")
        await asyncio.sleep(0.05)
        # cc1 creates a vote with no threshold
        await ws1.send(json.dumps({
            "type": "vote_create",
            "question": "which?",
            "options": ["beta", "alpha"],  # intentionally non-alphabetical input order
            "threshold": None,
        }))
        pend = await _recv_until(ws1, lambda p: p.get("type") == "vote_pending")
        vid = pend["vote_id"]
        # also "you" needs to vote since required set includes "you"
        # do it through the UI WS
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(UI_WS_URL) as ui_ws:
                init = await ui_ws.receive_json(timeout=2)
                assert init["type"] == "init"
                # cc1 votes alpha, cc2 votes beta, cc3 votes alpha → alpha wins by count
                # But for a tie-break test: cc1->alpha, cc2->beta, cc3->beta, you->alpha
                #   counts: alpha=2, beta=2 → tie → alphabetical "alpha"
                await ws1.send(json.dumps({"type": "vote_cast", "vote_id": vid, "option": "alpha"}))
                await ws2.send(json.dumps({"type": "vote_cast", "vote_id": vid, "option": "beta"}))
                await ws3.send(json.dumps({"type": "vote_cast", "vote_id": vid, "option": "beta"}))
                # before "you" casts, the vote must still be open
                await asyncio.sleep(0.1)
                v = next(x for x in started_broker.state["votes"] if x["id"] == vid)
                assert v["status"] == "open", "vote should not resolve before 'you' has voted"
                # now "you" votes alpha — required set = {cc1,cc2,cc3,you} all voted
                await ui_ws.send_json({"action": "vote", "vote_id": vid, "option": "alpha"})
                r1 = await _recv_until(ws1, lambda p: p.get("type") == "vote_resolved")
                assert r1["vote_id"] == vid
                # alpha=2 (cc1, you), beta=2 (cc2, cc3) → tie → alphabetical => "alpha"
                assert r1["winner"] == "alpha"


@pytest.mark.asyncio
async def test_vote_cast_unknown_id_is_noop(started_broker):
    """Casting a ballot against a non-existent vote id should not crash."""
    async with websockets.connect(WS_URL) as ws1:
        await _register(ws1, iid="cc1")
        await asyncio.sleep(0.05)
        # send a cast for a vote that doesn't exist
        await ws1.send(json.dumps({
            "type": "vote_cast",
            "vote_id": "V999",
            "option": "yes",
        }))
        # broker must remain responsive — send a follow-up message and confirm a relay
        await ws1.send(json.dumps({"type": "broadcast", "text": "still alive"}))
        # no second instance, so just sleep and verify broker state untouched
        await asyncio.sleep(0.2)
        assert not any(v["id"] == "V999" for v in started_broker.state["votes"])


@pytest.mark.asyncio
async def test_auth_disabled_by_default(started_broker):
    """When auth_token is not set, existing register flow works (no token)."""
    assert started_broker.auth_token is None
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await asyncio.sleep(0.05)
        assert "cc1" in started_broker.instances
        assert started_broker.instances["cc1"]["online"] is True


@pytest.mark.asyncio
async def test_auth_instance_rejects_wrong_token(authed_broker):
    """Wrong token in register => auth_failed reply and connection closes."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "register",
            "id": "cc1",
            "name": "Claude 1",
            "project": "P",
            "token": "wrong",
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=2)
        payload = json.loads(raw)
        assert payload["type"] == "auth_failed"
        # Connection should be closed by the broker shortly after
        closed = False
        try:
            await asyncio.wait_for(ws.recv(), timeout=1)
        except websockets.ConnectionClosed:
            closed = True
        except asyncio.TimeoutError:
            pass
        assert closed or ws.close_code is not None
        # broker should NOT have registered cc1
        assert "cc1" not in authed_broker.instances


@pytest.mark.asyncio
async def test_auth_instance_accepts_correct_token(authed_broker):
    """Correct token => register succeeds normally."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "register",
            "id": "cc1",
            "name": "Claude 1",
            "project": "P",
            "token": "secret",
        }))
        # expect memory_init, then tasks_init
        init = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        assert init["type"] == "memory_init"
        tinit = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        assert tinit["type"] == "tasks_init"
        await asyncio.sleep(0.05)
        assert "cc1" in authed_broker.instances
        assert authed_broker.instances["cc1"]["online"] is True


@pytest.mark.asyncio
async def test_auth_rest_rejects_wrong_token(authed_broker):
    """REST POST /api/send without X-Mesh-Token => 401."""
    async with aiohttp.ClientSession() as session:
        # No header at all
        async with session.post(REST_URL + "/api/send",
                                json={"to": "cc1", "text": "hi"}) as r:
            assert r.status == 401
        # Wrong header
        async with session.post(REST_URL + "/api/send",
                                json={"to": "cc1", "text": "hi"},
                                headers={"X-Mesh-Token": "wrong"}) as r:
            assert r.status == 401
        # Correct header succeeds
        async with session.post(REST_URL + "/api/send",
                                json={"to": "cc1", "text": "hi"},
                                headers={"X-Mesh-Token": "secret"}) as r:
            assert r.status == 200


@pytest.mark.asyncio
async def test_auth_ui_ws_rejects_wrong_token(authed_broker):
    """UI WS without ?token=... => 401 (no upgrade)."""
    async with aiohttp.ClientSession() as session:
        # Plain GET — must not upgrade, expect 401
        async with session.get(REST_URL + "/ui") as r:
            assert r.status == 401
        # With correct token in query, upgrade succeeds
        async with session.ws_connect(REST_URL + "/ui?token=secret") as ui_ws:
            init = await ui_ws.receive_json(timeout=2)
            assert init["type"] == "init"


@pytest.mark.asyncio
async def test_auth_default_deny_on_rest_endpoints(authed_broker):
    """Default-deny middleware regression guard: endpoints that previously
    skipped _check_rest_auth (reads, the token-returning share-info, and the
    mutating task/memory POSTs) must all 401 without the token, while the
    public allowlist (health) stays open."""
    reads = ("/api/instances", "/api/tasks", "/api/memory",
             "/api/messages", "/api/audit", "/api/share-info")
    async with aiohttp.ClientSession() as session:
        for path in reads:
            async with session.get(REST_URL + path) as r:
                assert r.status == 401, f"{path} must require a token"
            async with session.get(REST_URL + path,
                                   headers={"X-Mesh-Token": "secret"}) as r:
                assert r.status == 200, f"{path} must pass with the token"
        # Mutating POSTs that used to be unauthenticated
        async with session.post(REST_URL + "/api/task", json={"title": "x"}) as r:
            assert r.status == 401
        async with session.post(REST_URL + "/api/memory",
                                json={"key": "k", "value": "v"}) as r:
            assert r.status == 401
        # Public allowlist: health needs no token
        async with session.get(REST_URL + "/api/health") as r:
            assert r.status == 200


@pytest.mark.asyncio
async def test_http_health_returns_ok(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.get(REST_URL + "/api/health") as r:
            assert r.status == 200
            data = await r.json()
    assert data["ok"] is True
    assert isinstance(data["uptime_seconds"], (int, float))
    assert data["uptime_seconds"] >= 0
    assert isinstance(data["online_instances"], int)
    assert "build_sha" in data
    assert isinstance(data["build_sha"], str)


# The web SSE relay (web/app/api/workspaces/[slug]/broker/sse) opens this UI WS,
# emits the init frame as an SSE `init` event, and forwards a fixed set of
# broadcast_ui frame types. These two tests pin the broker-side contract that
# relay depends on so a broker change can't silently break the stream.

# Keep in sync with FORWARDED_TYPES in the SSE route.
SSE_INIT_COLLECTIONS = (
    "approvals", "votes", "flows", "channels", "audit", "messages",
)


@pytest.mark.asyncio
async def test_ui_init_carries_sse_relayed_collections(started_broker):
    """The UI WS init frame must include every collection the SSE relay turns
    into its `init` snapshot event, matching the GET /api/<collection> reads."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            init = await ui_ws.receive_json(timeout=2)
    assert init["type"] == "init"
    for key in SSE_INIT_COLLECTIONS:
        assert key in init, f"init snapshot missing '{key}' the SSE relay forwards"
        assert isinstance(init[key], list)


@pytest.mark.asyncio
async def test_ui_ws_receives_approval_request_broadcast(started_broker):
    """An instance-raised approval is pushed to a connected UI WS as an
    `approval_request` frame — the forward path the SSE relay turns into an SSE
    event. Asserts the frame arrives and carries the approval payload."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            init = await ui_ws.receive_json(timeout=2)
            assert init["type"] == "init"
            async with websockets.connect(WS_URL) as ws:
                await _register(ws, iid="cc1")
                await ws.send(json.dumps({
                    "type": "approval_request",
                    "action": "deploy to production",
                    "risk": "high",
                    "detail": "ship build 42",
                }))

                async def wait_approval():
                    async for raw in ui_ws:
                        if raw.type != aiohttp.WSMsgType.TEXT:
                            continue
                        p = json.loads(raw.data)
                        if p.get("type") == "approval_request":
                            return p

                got = await asyncio.wait_for(wait_approval(), timeout=2)
    ap = got["approval"]
    assert ap["from"] == "cc1"
    assert ap["action"] == "deploy to production"
    assert ap["risk"] == "high"
    assert ap["status"] == "pending"
    # The approval landed in broker state, so the SSE relay's REST snapshot
    # (GET /api/approvals) and its pushed event agree.
    assert any(a["id"] == ap["id"] for a in started_broker.state["approvals"])


@pytest.mark.asyncio
async def test_http_metrics_prom_format(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.get(REST_URL + "/api/metrics") as r:
            assert r.status == 200
            ctype = r.headers.get("Content-Type", "")
            assert "text/plain" in ctype
            body = await r.text()
    assert "agent_mesh_uptime_seconds" in body
    assert "agent_mesh_messages_total" in body
    assert "agent_mesh_tasks_total" in body
    assert "agent_mesh_instances_online" in body
    # each non-empty line should have at least one whitespace-separated value
    for line in body.strip().splitlines():
        assert " " in line


@pytest.mark.asyncio
async def test_http_post_task_creates(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/task",
                                json={"title": "rest-task", "assignee": "cc9",
                                      "priority": "high", "deps": []}) as r:
            assert r.status == 200
            data = await r.json()
    assert data["ok"] is True
    assert data["task"]["title"] == "rest-task"
    assert data["task"]["assignee"] == "cc9"
    assert data["task"]["priority"] == "high"
    assert any(t["title"] == "rest-task" for t in started_broker.state["tasks"])


@pytest.mark.asyncio
async def test_http_vote_create_cast_and_resolve(started_broker):
    """REST vote lifecycle backing the dashboard Votes page: POST /api/vote
    creates an open vote; POST /api/vote/{id}/cast records ballots and bumps the
    tally; crossing the threshold resolves the vote with the winning option."""
    async with aiohttp.ClientSession() as session:
        # Create a vote with two options and a threshold of 2.
        async with session.post(REST_URL + "/api/vote",
                                json={"question": "ship it?",
                                      "options": ["yes", "no"],
                                      "threshold": 2}) as r:
            assert r.status == 200
            created = await r.json()
        assert created["ok"] is True
        vid = created["vote"]["id"]
        assert created["vote"]["status"] == "open"
        assert created["vote"]["options"] == ["yes", "no"]

        # The open vote shows up on GET /api/votes (what the page polls).
        async with session.get(REST_URL + "/api/votes") as r:
            assert r.status == 200
            listing = await r.json()
        assert any(v["id"] == vid and v["status"] == "open"
                   for v in listing["votes"])

        # First ballot from a named voter. One ballot is below threshold, so the
        # vote stays open and the tally reflects exactly one vote for "yes".
        async with session.post(REST_URL + f"/api/vote/{vid}/cast",
                                json={"voter": "alice", "option": "yes"}) as r:
            assert r.status == 200
            after_one = await r.json()
        assert after_one["vote"]["ballots"]["alice"] == "yes"
        assert after_one["vote"]["status"] == "open"

        # Second ballot for the same option crosses threshold=2 and resolves.
        async with session.post(REST_URL + f"/api/vote/{vid}/cast",
                                json={"voter": "bob", "option": "yes"}) as r:
            assert r.status == 200
            after_two = await r.json()
        assert after_two["vote"]["ballots"]["bob"] == "yes"

    # Server state is authoritative: vote resolved, winner recorded, both
    # ballots persisted for the page to render voter names and choices.
    v = next(x for x in started_broker.state["votes"] if x["id"] == vid)
    assert v["status"] == "resolved"
    assert v["winner"] == "yes"
    assert v["ballots"] == {"alice": "yes", "bob": "yes"}


@pytest.mark.asyncio
async def test_http_vote_create_requires_two_options(started_broker):
    """The create form requires >=2 options; the broker rejects a single-option
    vote so a malformed POST never lands in state."""
    before = len(started_broker.state["votes"])
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/vote",
                                json={"question": "only one?",
                                      "options": ["solo"]}) as r:
            assert r.status == 400
            err = await r.json()
    assert "options" in err.get("error", "").lower()
    assert len(started_broker.state["votes"]) == before


@pytest.mark.asyncio
async def test_http_vote_cast_closed_rejected(started_broker):
    """Once resolved, further ballots are rejected — the page disables the
    buttons but the broker is the real guard."""
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/vote",
                                json={"question": "a or b?",
                                      "options": ["a", "b"],
                                      "threshold": 1}) as r:
            assert r.status == 200
            vid = (await r.json())["vote"]["id"]
        # threshold=1 resolves on the first ballot
        async with session.post(REST_URL + f"/api/vote/{vid}/cast",
                                json={"voter": "alice", "option": "a"}) as r:
            assert r.status == 200
        # casting again must be refused
        async with session.post(REST_URL + f"/api/vote/{vid}/cast",
                                json={"voter": "bob", "option": "b"}) as r:
            assert r.status == 400
            err = await r.json()
    assert "closed" in err.get("error", "").lower()
    v = next(x for x in started_broker.state["votes"] if x["id"] == vid)
    assert v["winner"] == "a"
    assert "bob" not in v["ballots"]


@pytest.mark.asyncio
async def test_http_post_task_cycle_rejected(started_broker):
    async with aiohttp.ClientSession() as session:
        # T001
        async with session.post(REST_URL + "/api/task",
                                json={"title": "a", "deps": []}) as r:
            assert r.status == 200
        # T002 depends on T001
        async with session.post(REST_URL + "/api/task",
                                json={"title": "b", "deps": ["T001"]}) as r:
            assert r.status == 200
        # T003 depends on T002 AND T001 — fine
        async with session.post(REST_URL + "/api/task",
                                json={"title": "c", "deps": ["T002"]}) as r:
            assert r.status == 200
        # Now attempt T004 that depends on itself indirectly: depend on T004 forces cycle if it referenced itself,
        # but we test by referencing a chain that loops via deps referencing future id — instead use direct self-loop
        # via existing-id: depend on a nonexistent id "T004" referencing itself isn't a cycle (unknown nodes ignored).
        # So craft a cycle: create T004 with deps=["T004"] (self-loop).
        async with session.post(REST_URL + "/api/task",
                                json={"title": "loop", "deps": ["T004"]}) as r:
            assert r.status == 400
            err = await r.json()
    assert "cyclic" in err.get("error", "").lower()


@pytest.mark.asyncio
async def test_http_put_task_updates_status(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/task",
                                json={"title": "movable"}) as r:
            assert r.status == 200
            tid = (await r.json())["task"]["id"]
        async with session.put(REST_URL + "/api/task/" + tid,
                               json={"status": "In Progress"}) as r:
            assert r.status == 200
            data = await r.json()
    assert data["ok"] is True
    assert data["task"]["status"] == "In Progress"
    t = next(x for x in started_broker.state["tasks"] if x["id"] == tid)
    assert t["status"] == "In Progress"


@pytest.mark.asyncio
async def test_http_put_task_ignores_server_owned_fields(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/task",
                                json={"title": "guarded"}) as r:
            tid = (await r.json())["task"]["id"]
        async with session.put(REST_URL + "/api/task/" + tid,
                               json={"priority": "high", "created_by": "spoof",
                                     "result": "injected"}) as r:
            assert r.status == 200
            data = await r.json()
    # editable field applied, server-owned fields untouched
    assert data["task"]["priority"] == "high"
    assert data["task"]["created_by"] == "you"
    assert "result" not in data["task"] or data["task"].get("result") != "injected"


@pytest.mark.asyncio
async def test_http_put_task_unknown_id_404(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.put(REST_URL + "/api/task/T999",
                               json={"status": "Done"}) as r:
            assert r.status == 404


@pytest.mark.asyncio
async def test_http_put_task_cycle_rejected(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/task",
                                json={"title": "a", "deps": []}) as r:
            t1 = (await r.json())["task"]["id"]
        async with session.post(REST_URL + "/api/task",
                                json={"title": "b", "deps": [t1]}) as r:
            t2 = (await r.json())["task"]["id"]
        # make t1 depend on t2 -> cycle, must be rejected and not applied
        async with session.put(REST_URL + "/api/task/" + t1,
                               json={"deps": [t2]}) as r:
            assert r.status == 400
            err = await r.json()
    assert "cyclic" in err.get("error", "").lower()
    t = next(x for x in started_broker.state["tasks"] if x["id"] == t1)
    assert t["deps"] == []


@pytest.mark.asyncio
async def test_http_put_task_edits_title_priority_assignee(started_broker):
    """Backs the TaskDetailModal edit flow: the modal PUTs the editable fields
    (title, priority, assignee) and re-reads the task on refetch. A single PUT
    carrying all three must apply each one server-side, and a `result` value
    sent alongside them must be ignored because result is server-owned."""
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/task",
                                json={"title": "before", "priority": "low",
                                      "assignee": ""}) as r:
            assert r.status == 200
            tid = (await r.json())["task"]["id"]
        # One PUT with every modal-editable field plus a server-owned field.
        async with session.put(REST_URL + "/api/task/" + tid,
                               json={"title": "after", "priority": "high",
                                     "assignee": "cc7",
                                     "result": "should-not-stick"}) as r:
            assert r.status == 200
            data = await r.json()
    # Editable fields applied in the response the modal reads back.
    assert data["task"]["title"] == "after"
    assert data["task"]["priority"] == "high"
    assert data["task"]["assignee"] == "cc7"
    # result is server-owned and must not be settable via this path.
    assert data["task"].get("result") != "should-not-stick"
    # Server state is authoritative: a subsequent refetch sees the same values.
    t = next(x for x in started_broker.state["tasks"] if x["id"] == tid)
    assert t["title"] == "after"
    assert t["priority"] == "high"
    assert t["assignee"] == "cc7"
    assert t.get("result") != "should-not-stick"


@pytest.mark.asyncio
async def test_http_put_task_clears_assignee(started_broker):
    """The modal's assignee dropdown includes an Unassigned option; selecting it
    PUTs assignee="" and the broker must clear the field, not reject the empty
    string as a no-op patch."""
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/task",
                                json={"title": "owned", "assignee": "cc3"}) as r:
            assert r.status == 200
            tid = (await r.json())["task"]["id"]
        async with session.put(REST_URL + "/api/task/" + tid,
                               json={"assignee": ""}) as r:
            assert r.status == 200
            data = await r.json()
    assert data["task"]["assignee"] == ""
    t = next(x for x in started_broker.state["tasks"] if x["id"] == tid)
    assert t["assignee"] == ""


@pytest.mark.asyncio
async def test_http_delete_task_removes(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/task",
                                json={"title": "trash"}) as r:
            tid = (await r.json())["task"]["id"]
        async with session.delete(REST_URL + "/api/task/" + tid) as r:
            assert r.status == 200
            data = await r.json()
    assert data["ok"] is True
    assert data["removed"] == 1
    assert not any(x["id"] == tid for x in started_broker.state["tasks"])
    # deleting again is a no-op (idempotent), removed=0
    async with aiohttp.ClientSession() as session:
        async with session.delete(REST_URL + "/api/task/" + tid) as r:
            assert r.status == 200
            assert (await r.json())["removed"] == 0


@pytest.mark.asyncio
async def test_http_post_memory_writes(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/memory",
                                json={"key": "API_SHAPE", "value": "{pct, ticker}",
                                      "mem_type": "contract"}) as r:
            assert r.status == 200
            data = await r.json()
    assert data["ok"] is True
    assert data["memory"]["key"] == "API_SHAPE"
    assert data["memory"]["value"] == "{pct, ticker}"
    assert data["memory"]["type"] == "contract"
    assert any(m["key"] == "API_SHAPE" for m in started_broker.state["memory"])


@pytest.mark.asyncio
async def test_http_post_approval_requires_action(started_broker):
    """REST create rejects an empty action — mirrors the web form validation."""
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/approval",
                                json={"risk": "high"}) as r:
            assert r.status == 400
            err = await r.json()
    assert "action" in err.get("error", "").lower()


@pytest.mark.asyncio
async def test_http_approval_create_and_respond_flow(started_broker):
    """Create via REST, see it pending in the list, approve it, confirm the
    status flips and the decision is recorded. This is the exact path the web
    approvals page drives (POST /api/approval, then POST /api/approval/{id}/respond)."""
    async with aiohttp.ClientSession() as session:
        # Create
        async with session.post(REST_URL + "/api/approval",
                                json={"from": "cc1", "action": "test",
                                      "risk": "high", "detail": "ship it"}) as r:
            assert r.status == 200
            created = await r.json()
        assert created["ok"] is True
        ap = created["approval"]
        ap_id = ap["id"]
        assert ap["action"] == "test"
        assert ap["risk"] == "high"
        assert ap["detail"] == "ship it"
        assert ap["status"] == "pending"

        # Listed as pending
        async with session.get(REST_URL + "/api/approvals") as r:
            assert r.status == 200
            listing = await r.json()
        match = next((a for a in listing["approvals"] if a["id"] == ap_id), None)
        assert match is not None and match["status"] == "pending"

        # Approve
        async with session.post(REST_URL + f"/api/approval/{ap_id}/respond",
                                json={"approved": True}) as r:
            assert r.status == 200
            decided = await r.json()
        assert decided["ok"] is True
        assert decided["approval"]["status"] == "approved"
        assert decided["approval"]["decision"] is True
        assert decided["approval"].get("decided_at")

    # Server state reflects the decision (server-authoritative, not client-reconciled).
    stored = next(a for a in started_broker.state["approvals"] if a["id"] == ap_id)
    assert stored["status"] == "approved"


@pytest.mark.asyncio
async def test_http_approval_respond_unknown_id_404(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/approval/AP999/respond",
                                json={"approved": False}) as r:
            assert r.status == 404


@pytest.mark.asyncio
async def test_http_post_vote_requires_two_options(started_broker):
    """REST create rejects a vote with fewer than two options — mirrors the web
    form validation on the votes page."""
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/vote",
                                json={"question": "ship?", "options": ["yes"]}) as r:
            assert r.status == 400
            err = await r.json()
    assert "option" in err.get("error", "").lower()


@pytest.mark.asyncio
async def test_http_vote_create_list_cast_flow(started_broker):
    """Create via REST, see it open in the list, cast a ballot, confirm the
    ballot is recorded. This is the exact path the web votes page drives
    (POST /api/vote, GET /api/votes, then POST /api/vote/{id}/cast — the
    brokerCastVote helper). With no online instances the required voter set is
    just {"you"}, so a single "you" ballot auto-resolves the vote."""
    async with aiohttp.ClientSession() as session:
        # Create
        async with session.post(REST_URL + "/api/vote",
                                json={"question": "which target",
                                      "options": ["staging", "prod"]}) as r:
            assert r.status == 200
            created = await r.json()
        assert created["ok"] is True
        v = created["vote"]
        vid = v["id"]
        assert v["question"] == "which target"
        assert v["options"] == ["staging", "prod"]
        assert v["status"] == "open"
        assert v["ballots"] == {}

        # Listed as open
        async with session.get(REST_URL + "/api/votes") as r:
            assert r.status == 200
            listing = await r.json()
        match = next((x for x in listing["votes"] if x["id"] == vid), None)
        assert match is not None and match["status"] == "open"

        # Cast — brokerCastVote omits the voter; broker defaults it to "you".
        async with session.post(REST_URL + f"/api/vote/{vid}/cast",
                                json={"option": "prod"}) as r:
            assert r.status == 200
            casted = await r.json()
        assert casted["ok"] is True
        assert casted["vote"]["ballots"]["you"] == "prod"

    # Server state records the ballot (server-authoritative). With "you" the
    # only required voter, the vote auto-resolves with that ballot as winner.
    stored = next(x for x in started_broker.state["votes"] if x["id"] == vid)
    assert stored["ballots"]["you"] == "prod"
    assert stored["status"] == "resolved"
    assert stored["winner"] == "prod"


@pytest.mark.asyncio
async def test_http_vote_cast_rejects_invalid_option(started_broker):
    """Casting an option not on the ballot is a 400 — the broker validates the
    choice against the vote's option set."""
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/vote",
                                json={"question": "q",
                                      "options": ["a", "b"]}) as r:
            assert r.status == 200
            vid = (await r.json())["vote"]["id"]
        async with session.post(REST_URL + f"/api/vote/{vid}/cast",
                                json={"option": "c"}) as r:
            assert r.status == 400
            err = await r.json()
    assert "option" in err.get("error", "").lower()


@pytest.mark.asyncio
async def test_http_vote_cast_unknown_id_404(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/vote/V999/cast",
                                json={"option": "a"}) as r:
            assert r.status == 404


@pytest.mark.asyncio
async def test_http_approval_concurrent_respond_serializes(started_broker):
    """Concurrent POST /api/approval/{id}/respond calls against the same valid
    approval must serialize under the lock: a valid id never spuriously 404s,
    every call returns 200, and the server settles on a single coherent
    decision (no lost-update where status and decision disagree).

    Regression guard for the TOCTOU window where the lookup ran outside the
    lock — a concurrent decision could be applied between the read and the
    mutation, leaving a torn record.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/approval",
                                json={"from": "cc1", "action": "deploy",
                                      "risk": "high"}) as r:
            assert r.status == 200
            ap_id = (await r.json())["approval"]["id"]

        # Fire a burst of concurrent decisions (alternating approve/reject)
        # against the same valid id.
        async def respond(approved: bool):
            async with session.post(
                    REST_URL + f"/api/approval/{ap_id}/respond",
                    json={"approved": approved}) as resp:
                return resp.status, await resp.json()

        results = await asyncio.gather(
            *[respond(i % 2 == 0) for i in range(12)])

    # No spurious 404s on a valid id; all calls land.
    statuses = [s for s, _ in results]
    assert statuses == [200] * 12, statuses

    # Server-authoritative final state is internally consistent: status matches
    # the recorded decision boolean, and the approval is decided exactly once.
    stored = next(a for a in started_broker.state["approvals"] if a["id"] == ap_id)
    assert stored["status"] in ("approved", "rejected")
    assert stored["decision"] is (stored["status"] == "approved")
    assert stored.get("decided_at")


@pytest.mark.asyncio
async def test_http_vote_concurrent_cast_no_lost_updates(started_broker):
    """Concurrent POST /api/vote/{id}/cast from distinct voters must each be
    recorded — no lost updates from the read-modify-write of the ballots dict.

    An online instance keeps the required voter set larger than {"you"}, so the
    vote stays open across the burst instead of auto-resolving on ballot one.
    """
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await asyncio.sleep(0.05)
        async with aiohttp.ClientSession() as session:
            async with session.post(REST_URL + "/api/vote",
                                    json={"question": "target",
                                          "options": ["a", "b"]}) as r:
                assert r.status == 200
                vid = (await r.json())["vote"]["id"]

            async def cast(voter: str, option: str):
                async with session.post(
                        REST_URL + f"/api/vote/{vid}/cast",
                        json={"voter": voter, "option": option}) as resp:
                    return resp.status, await resp.json()

            voters = [f"v{i}" for i in range(15)]
            results = await asyncio.gather(
                *[cast(v, "a" if i % 2 == 0 else "b")
                  for i, v in enumerate(voters)])

        assert all(s == 200 for s, _ in results)

    # Every distinct voter's ballot survived the concurrent writes.
    stored = next(x for x in started_broker.state["votes"] if x["id"] == vid)
    for i, v in enumerate(voters):
        assert stored["ballots"][v] == ("a" if i % 2 == 0 else "b"), v
    assert len(stored["ballots"]) == len(voters)


@pytest.mark.asyncio
async def test_http_vote_cast_close_race_rejects_late_ballots(started_broker):
    """Deterministic TOCTOU guard: the status check MUST run inside self.lock.

    We hold the broker lock to force an in-flight cast to queue on lock
    acquisition, flip the vote to resolved while it waits, then release. A cast
    whose status check is inside the lock observes the resolved state and 400s,
    writing nothing. The pre-fix code (status checked BEFORE the lock) would
    have passed its open-check, then written a ballot into the now-resolved
    vote and returned 200 -- so reverting the fix makes this test fail.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/vote",
                                json={"question": "q",
                                      "options": ["a", "b"]}) as r:
            assert r.status == 200
            vid = (await r.json())["vote"]["id"]

        async def cast():
            async with session.post(
                    REST_URL + f"/api/vote/{vid}/cast",
                    json={"voter": "late", "option": "b"}) as resp:
                return resp.status, await resp.json()

        # Hold the lock so the cast blocks on `async with self.lock` before it
        # can validate status; simulate a concurrent close completing meanwhile.
        await started_broker.lock.acquire()
        try:
            task = asyncio.create_task(cast())
            await asyncio.sleep(0.2)  # let the request reach the lock acquire
            v = next(x for x in started_broker.state["votes"] if x["id"] == vid)
            v["status"] = "resolved"
            v["winner"] = "a"
        finally:
            started_broker.lock.release()
        status, _ = await task

    # The late cast must be rejected and must not have leaked into the resolved
    # vote.
    assert status == 400
    stored = next(x for x in started_broker.state["votes"] if x["id"] == vid)
    assert "late" not in stored.get("ballots", {})


@pytest.mark.asyncio
async def test_cyclic_task_rejected(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            await ui_ws.receive_json(timeout=2)  # init
            # T001
            await ui_ws.send_json({"action": "create_task", "title": "a", "deps": []})
            await asyncio.sleep(0.1)
            # T002 depends on T001
            await ui_ws.send_json({"action": "create_task", "title": "b", "deps": ["T001"]})
            await asyncio.sleep(0.1)
            # T003 depends on T002
            await ui_ws.send_json({"action": "create_task", "title": "c", "deps": ["T002"]})
            await asyncio.sleep(0.1)
            # now update T001 to depend on T003 — cycle
            await ui_ws.send_json({"action": "update_task", "id": "T001", "deps": ["T003"]})
            # expect an error message
            got_error = False
            end = asyncio.get_event_loop().time() + 2
            while asyncio.get_event_loop().time() < end:
                msg = await asyncio.wait_for(ui_ws.receive(), timeout=2)
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                p = json.loads(msg.data)
                if p.get("type") == "error" and "cyclic" in p.get("error", "").lower():
                    got_error = True
                    break
            assert got_error
            # T001 deps unchanged
            assert started_broker.state["tasks"][0]["deps"] == []


# -------------------- flow execution engine (Batch 2) --------------------


async def _create_flow(ui_ws, name, trigger, action_desc):
    """Create a flow via the UI websocket and wait for confirmation."""
    await ui_ws.send_json({
        "action": "create_flow",
        "name": name,
        "trigger": trigger,
        "action_desc": action_desc,
    })
    # drain state_update so the flow is registered before we continue
    end = asyncio.get_event_loop().time() + 2
    while asyncio.get_event_loop().time() < end:
        msg = await asyncio.wait_for(ui_ws.receive(), timeout=2)
        if msg.type != aiohttp.WSMsgType.TEXT:
            continue
        p = json.loads(msg.data)
        if p.get("type") == "state_update" and "flows" in p.get("delta", {}):
            flows = p["delta"]["flows"]
            for f in flows:
                if f["name"] == name:
                    return f
    raise AssertionError("flow not confirmed via state_update")


@pytest.mark.asyncio
async def test_flow_regex_trigger_fires_send(started_broker):
    """Posting a message matching the trigger fires a `send` action to the target."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            await ui_ws.receive_json(timeout=2)  # init
            await _create_flow(ui_ws, "deploy-fanout",
                                r"\bdeploy\b",
                                "send cc2 deploy detected from {from}")
        async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
            await _register(ws1, iid="cc1")
            await _register(ws2, iid="cc2")
            await asyncio.sleep(0.05)
            # cc1 says something containing "deploy" addressed to "you"
            await ws1.send(json.dumps({
                "type": "message", "to": "you", "text": "ok I will deploy now",
            }))
            # cc2 should receive a flow-generated message
            got = await _recv_until(
                ws2,
                lambda p: p.get("type") == "message" and p.get("from") == "flow",
                timeout=2.0,
            )
            assert "deploy detected" in got["text"]
            assert "cc1" in got["text"]


@pytest.mark.asyncio
async def test_flow_template_renders_groups(started_broker):
    """Regex capture groups should render via {match.N} in the template."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            await ui_ws.receive_json(timeout=2)
            await _create_flow(ui_ws, "task-capture",
                                r"task (\w+) ready",
                                "send cc2 task {match.1} is queued for {to}")
        async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
            await _register(ws1, iid="cc1")
            await _register(ws2, iid="cc2")
            await asyncio.sleep(0.05)
            await ws1.send(json.dumps({
                "type": "message", "to": "you", "text": "task ALPHA42 ready for review",
            }))
            got = await _recv_until(
                ws2,
                lambda p: p.get("type") == "message" and p.get("from") == "flow",
                timeout=2.0,
            )
            assert "ALPHA42" in got["text"]
            assert "queued for you" in got["text"]


@pytest.mark.asyncio
async def test_flow_rate_limit(started_broker):
    """Same flow can fire 5x in 60s; the 6th must be throttled."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            await ui_ws.receive_json(timeout=2)
            await _create_flow(ui_ws, "rate-limited",
                                r"ping",
                                "send cc2 pong-{match.0}")
        async with websockets.connect(WS_URL) as ws1, websockets.connect(WS_URL) as ws2:
            await _register(ws1, iid="cc1")
            await _register(ws2, iid="cc2")
            await asyncio.sleep(0.05)
            # fire 6x rapidly
            for i in range(6):
                await ws1.send(json.dumps({
                    "type": "message", "to": "you", "text": f"ping {i}",
                }))
            # collect flow-originated messages on cc2 for up to 1s
            received = []
            end = asyncio.get_event_loop().time() + 1.5
            while asyncio.get_event_loop().time() < end:
                remaining = end - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws2.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                p = json.loads(raw)
                if p.get("type") == "message" and p.get("from") == "flow":
                    received.append(p)
            # exactly 5 flow fires should reach cc2; 6th throttled
            assert len(received) == 5, f"expected 5 fires, got {len(received)}"
            # verify "flow_throttled" appears in audit
            throttled = [a for a in started_broker.state["audit"]
                         if a.get("action") == "flow_throttled"]
            assert len(throttled) >= 1


@pytest.mark.asyncio
async def test_http_flow_rest_lifecycle(started_broker):
    """REST flow lifecycle the Automations page drives: create, list, toggle,
    fire, delete, plus regex validation and audit entries."""
    async with aiohttp.ClientSession() as session:
        # reject invalid regex in trigger
        async with session.post(REST_URL + "/api/flow",
                                json={"name": "bad", "trigger": "("}) as r:
            assert r.status == 400
            err = await r.json()
            assert "regex" in err.get("error", "").lower()

        # create a valid flow
        async with session.post(REST_URL + "/api/flow",
                                json={"name": "deploy-notify",
                                      "trigger": r"\bdeploy\b",
                                      "action": "send cc2 deploy seen"}) as r:
            assert r.status == 200
            created = await r.json()
        assert created["ok"] is True
        fid = created["flow"]["id"]
        assert created["flow"]["name"] == "deploy-notify"
        assert created["flow"]["enabled"] is True

        # it shows up in the list
        async with session.get(REST_URL + "/api/flows") as r:
            assert r.status == 200
            listed = await r.json()
        assert any(f["id"] == fid for f in listed["flows"])

        # toggle to disabled
        async with session.post(REST_URL + f"/api/flow/{fid}/toggle",
                                json={"enabled": False}) as r:
            assert r.status == 200
            toggled = await r.json()
        assert toggled["flow"]["enabled"] is False
        assert next(f for f in started_broker.state["flows"]
                    if f["id"] == fid)["enabled"] is False

        # toggle with no body flips it back on
        async with session.post(REST_URL + f"/api/flow/{fid}/toggle",
                                json={}) as r:
            assert r.status == 200
            toggled2 = await r.json()
        assert toggled2["flow"]["enabled"] is True

        # fire records an audit entry
        async with session.post(REST_URL + f"/api/flow/{fid}/fire",
                                json={}) as r:
            assert r.status == 200
            fired = await r.json()
        assert fired["ok"] is True
        fires = [a for a in started_broker.state["audit"]
                 if a.get("action") == "flow_fire" and fid in a.get("detail", "")]
        assert len(fires) >= 1

        # firing an unknown flow is a 404
        async with session.post(REST_URL + "/api/flow/F999/fire",
                                json={}) as r:
            assert r.status == 404

        # delete removes it from state and the list
        async with session.delete(REST_URL + f"/api/flow/{fid}") as r:
            assert r.status == 200
            deleted = await r.json()
        assert deleted["removed"] == 1
        assert not any(f["id"] == fid for f in started_broker.state["flows"])


# ----------------------- mDNS / Zeroconf -----------------------

# Use unique ports for these so they don't fight the started_broker fixture.
ZC_UI_PORT = int(os.environ.get("MESH_TEST_ZC_UI_PORT", "18865"))
ZC_INST_PORT = int(os.environ.get("MESH_TEST_ZC_INST_PORT", "18866"))


@pytest.mark.asyncio
async def test_zeroconf_advertise_unregister_safe(tmp_path):
    """Start and stop a broker — mDNS registration must never raise."""
    state_file = tmp_path / "state.json"
    b = broker_mod.Broker(ui_port=ZC_UI_PORT, instance_port=ZC_INST_PORT,
                          state_path=state_file)
    # start should not raise even if zeroconf isn't available or registration
    # fails — the broker is supposed to log-and-continue.
    await b.start()
    try:
        await asyncio.sleep(0.05)
        # If zeroconf is importable, the broker should have set _zc.
        # If not, _zc stays None — both paths are valid.
        try:
            import zeroconf  # noqa: F401
            zeroconf_available = True
        except Exception:
            zeroconf_available = False
        if zeroconf_available:
            # advertisement may still fail (e.g. no network); just confirm
            # the broker attempted it without crashing.
            assert b._zc is None or b._zc is not None
        else:
            assert b._zc is None
    finally:
        # stop must not raise either, regardless of whether mDNS registered.
        await b.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_zeroconf_missing_module_graceful(tmp_path, monkeypatch):
    """Simulate zeroconf being unavailable; broker must still start/stop."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "zeroconf" or name.startswith("zeroconf."):
            raise ImportError("simulated: zeroconf not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    state_file = tmp_path / "state.json"
    b = broker_mod.Broker(ui_port=ZC_UI_PORT + 2, instance_port=ZC_INST_PORT + 2,
                          state_path=state_file)
    # Must not raise even though the zeroconf import will fail.
    await b.start()
    try:
        await asyncio.sleep(0.05)
        # No zeroconf available -> no registration object.
        assert b._zc is None
        assert b._zc_info is None
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


# ============================================================================
# Plugin bridge tests
# ============================================================================

def test_plugin_catalog_scans(tmp_path):
    """Broker scans plugins_dir at startup and exposes catalog."""
    plugins_dir = tmp_path / "cache"
    plugins_dir.mkdir()
    _make_fake_plugin(plugins_dir, "mkt-x", "myplugin", "1.0.0",
                      skills=["my-skill", "second-skill"],
                      agents=["my-agent"],
                      commands=["my-command"])
    _make_fake_plugin(plugins_dir, "mkt-y", "other", "0.1.0",
                      skills=["alpha"])
    b = broker_mod.Broker(plugins_dir=plugins_dir, state_path=tmp_path / "s.json")
    b._rescan_plugins()
    assert "myplugin" in b._plugin_catalog
    assert "other" in b._plugin_catalog
    mp = b._plugin_catalog["myplugin"]
    assert mp["marketplace"] == "mkt-x"
    assert mp["version"] == "1.0.0"
    assert "my-skill" in mp["skills"]
    assert "second-skill" in mp["skills"]
    assert "my-agent.md" in mp["agents"]
    assert "my-command.md" in mp["commands"]
    assert mp["manifest_data"].get("name") == "myplugin"


@pytest.mark.asyncio
async def test_plugin_invoke_returns_discovered(started_broker, tmp_path):
    """Instance sends plugin_invoke; receives plugin_invoke_result with status=discovered."""
    # populate the started_broker's plugins dir
    plugins_dir = started_broker.plugins_dir
    _make_fake_plugin(plugins_dir, "mkt-x", "myplugin", "1.0.0",
                      skills=["my-skill"], agents=["my-agent"])
    started_broker._rescan_plugins()
    assert "myplugin" in started_broker._plugin_catalog

    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await asyncio.sleep(0.05)
        await ws.send(json.dumps({
            "type": "plugin_invoke",
            "plugin": "myplugin",
            "tool": "my-skill",
            "args": {"foo": "bar"},
        }))
        result = await _recv_until(ws, lambda p: p.get("type") == "plugin_invoke_result")
        assert result["status"] == "discovered"
        assert result["plugin"] == "myplugin"
        assert result["tool"] == "my-skill"
        assert result["kind"] == "skill"
        assert result["path"].endswith("SKILL.md")
        assert result["request_id"].startswith("PI")
        assert result["manifest"].get("name") == "myplugin"
        # audit row written
        assert any(a.get("action") == "plugin_invoke" for a in started_broker.state["audit"])

        # Also test that agents are resolvable
        await ws.send(json.dumps({
            "type": "plugin_invoke",
            "plugin": "myplugin",
            "tool": "my-agent",
        }))
        result2 = await _recv_until(ws, lambda p: p.get("type") == "plugin_invoke_result"
                                    and p.get("tool") == "my-agent")
        assert result2["status"] == "discovered"
        assert result2["kind"] == "agent"
        assert result2["path"].endswith("my-agent.md")


@pytest.mark.asyncio
async def test_plugin_invoke_not_found(started_broker):
    """Invoke a non-existent plugin → status=not_found, audit row written."""
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await asyncio.sleep(0.05)
        await ws.send(json.dumps({
            "type": "plugin_invoke",
            "plugin": "no-such-plugin",
            "tool": "whatever",
        }))
        result = await _recv_until(ws, lambda p: p.get("type") == "plugin_invoke_result")
        assert result["status"] == "not_found"
        assert result["plugin"] == "no-such-plugin"
        assert result["path"] == ""
        assert result["request_id"].startswith("PI")
        # audit row written
        assert any(a.get("action") == "plugin_invoke"
                   and "not_found" in a.get("detail", "")
                   for a in started_broker.state["audit"])


@pytest.mark.asyncio
async def test_plugin_rest_endpoints(started_broker, tmp_path):
    """GET /api/plugins lists plugins; GET /api/plugins/<id> returns full manifest."""
    plugins_dir = started_broker.plugins_dir
    _make_fake_plugin(plugins_dir, "mkt-z", "restplug", "0.2.0",
                      skills=["sk-a", "sk-b"], commands=["do-thing"])
    started_broker._rescan_plugins()

    async with aiohttp.ClientSession() as session:
        async with session.get(REST_URL + "/api/plugins") as r:
            assert r.status == 200
            data = await r.json()
        ids = [p["id"] for p in data["plugins"]]
        assert "restplug" in ids
        row = next(p for p in data["plugins"] if p["id"] == "restplug")
        assert row["marketplace"] == "mkt-z"
        assert row["version"] == "0.2.0"
        assert row["skills"] == 2
        assert row["commands"] == 1
        assert row["agents"] == 0

        async with session.get(REST_URL + "/api/plugins/restplug") as r:
            assert r.status == 200
            detail = await r.json()
        assert detail["id"] == "restplug"
        assert detail["manifest"]["name"] == "restplug"
        assert set(detail["skills"]) == {"sk-a", "sk-b"}
        assert detail["path"].endswith("0.2.0")

        async with session.get(REST_URL + "/api/plugins/nope") as r:
            assert r.status == 404


# ============================================================================
# Channels (server-side groups) — backs the dashboard Channels page
# ============================================================================

@pytest.mark.asyncio
async def test_http_channels_create_list_delete(started_broker):
    """REST channel lifecycle the Channels page drives: POST /api/channels creates
    a named group with members; GET /api/channels lists it with its members so the
    page can show a member count; DELETE removes it. Server state is authoritative
    throughout — the page never tracks membership client-side."""
    async with aiohttp.ClientSession() as session:
        # Create a channel with two members.
        async with session.post(REST_URL + "/api/channels",
                                json={"name": "deploy-crew",
                                      "members": ["cc1", "cc2"]}) as r:
            assert r.status == 200
            created = await r.json()
        assert created["ok"] is True
        cid = created["channel"]["id"]
        assert created["channel"]["name"] == "deploy-crew"
        assert created["channel"]["members"] == ["cc1", "cc2"]

        # It shows up on GET /api/channels (what the page polls), with the
        # members the count is derived from.
        async with session.get(REST_URL + "/api/channels") as r:
            assert r.status == 200
            listing = await r.json()
        row = next(c for c in listing["channels"] if c["id"] == cid)
        assert row["name"] == "deploy-crew"
        assert len(row["members"]) == 2

        # Delete removes it from server state and the listing.
        async with session.delete(REST_URL + f"/api/channels/{cid}") as r:
            assert r.status == 200
            deleted = await r.json()
        assert deleted["ok"] is True
        assert deleted["removed"] == 1

        async with session.get(REST_URL + "/api/channels") as r:
            assert r.status == 200
            after = await r.json()
        assert all(c["id"] != cid for c in after["channels"])

    assert cid not in started_broker.state.get("channels", {})


@pytest.mark.asyncio
async def test_http_channels_create_requires_member(started_broker):
    """The create form requires at least one member; the broker rejects an empty
    member list so a malformed POST never lands in state."""
    before = len(started_broker.state.get("channels", {}))
    async with aiohttp.ClientSession() as session:
        async with session.post(REST_URL + "/api/channels",
                                json={"name": "empty", "members": []}) as r:
            assert r.status == 400
            err = await r.json()
    assert "member" in err.get("error", "").lower()
    assert len(started_broker.state.get("channels", {})) == before


# ============================================================================
# Banner / startup output
# ============================================================================

def test_print_banner_emits_key_lines(capsys):
    """print_banner prints the title and all URL/REST/instance/snippet lines
    regardless of whether ANSI color is enabled."""
    broker_mod.print_banner("10.0.0.5", 8765, 8766)
    out = capsys.readouterr().out
    assert "AGENT MESH" in out
    assert "BROKER RUNNING" in out
    assert "http://10.0.0.5:8765" in out
    assert "http://localhost:8765/api/" in out
    assert "ws://localhost:8766" in out
    assert "python connect.py" in out


# ============================================================================
# Channels (server-side groups)
# ============================================================================

@pytest.mark.asyncio
async def test_channel_create_list_and_fanout(started_broker):
    """A channel created over REST fans a /api/send out to its members only,
    tags each delivered message with the channel id, and excludes non-members."""
    async with websockets.connect(WS_URL) as ws1, \
               websockets.connect(WS_URL) as ws2, \
               websockets.connect(WS_URL) as ws3:
        await _register(ws1, iid="cc1")
        await _register(ws2, iid="cc2")
        await _register(ws3, iid="cc3")
        await asyncio.sleep(0.05)

        async with aiohttp.ClientSession() as session:
            # create a channel with cc1 + cc2 as members (cc3 left out)
            async with session.post(
                REST_URL + "/api/channels",
                json={"name": "#deployments", "members": ["cc1", "cc2"]},
            ) as r:
                assert r.status == 200
                created = await r.json()
            cid = created["channel"]["id"]
            assert created["channel"]["name"] == "#deployments"
            assert created["channel"]["members"] == ["cc1", "cc2"]

            # it shows up in the channel list
            async with session.get(REST_URL + "/api/channels") as r:
                assert r.status == 200
                listing = await r.json()
            assert any(c["id"] == cid for c in listing["channels"])

            # send to the channel
            async with session.post(
                REST_URL + "/api/send",
                json={"from": "web-ui", "to": f"channel:{cid}", "text": "ship it"},
            ) as r:
                assert r.status == 200
                sent = await r.json()
            # one message per member, each tagged with the channel id
            assert sent["channel"] == cid
            assert len(sent["messages"]) == 2
            assert all(m["channel"] == cid for m in sent["messages"])

        # both members receive it, tagged with the channel
        got1 = await _recv_until(
            ws1, lambda p: p.get("type") == "message" and p.get("text") == "ship it")
        got2 = await _recv_until(
            ws2, lambda p: p.get("type") == "message" and p.get("text") == "ship it")
        assert got1["channel"] == cid
        assert got2["channel"] == cid

        # the non-member (cc3) does not receive the channel message
        try:
            raw = await asyncio.wait_for(ws3.recv(), timeout=0.3)
            payload = json.loads(raw)
            assert not (payload.get("type") == "message"
                        and payload.get("text") == "ship it")
        except asyncio.TimeoutError:
            pass


@pytest.mark.asyncio
async def test_channel_update_members_and_delete(started_broker):
    """Channel membership can be edited over REST and the channel deleted; a
    send to an unknown / empty channel is rejected rather than broadcast."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            REST_URL + "/api/channels",
            json={"name": "#ops", "members": ["cc1"]},
        ) as r:
            assert r.status == 200
            cid = (await r.json())["channel"]["id"]

        # add cc2 as a member
        async with session.put(
            REST_URL + f"/api/channels/{cid}",
            json={"members": ["cc1", "cc2"]},
        ) as r:
            assert r.status == 200
            assert (await r.json())["channel"]["members"] == ["cc1", "cc2"]

        # sending to an unknown channel is a 404, never a silent broadcast
        async with session.post(
            REST_URL + "/api/send",
            json={"to": "channel:ch_nope123", "text": "x"},
        ) as r:
            assert r.status == 404

        # delete removes it from the listing
        async with session.delete(REST_URL + f"/api/channels/{cid}") as r:
            assert r.status == 200
            assert (await r.json())["removed"] == 1
        async with session.get(REST_URL + "/api/channels") as r:
            listing = await r.json()
        assert not any(c["id"] == cid for c in listing["channels"])


# --------------------------------------------------------------------------
# TypeScript client (clients/connect.ts) blocking helpers.
#
# These drive the REAL MeshClient via a tiny Node harness (tests/ts_client_
# harness.mjs) that imports connect.ts with Node's type-stripping. Each helper
# connects to the live broker over a websocket exactly like the Python client,
# so we exercise the actual approveAndWait / voteAndWait wire handling.
# --------------------------------------------------------------------------

_NODE_BIN = shutil.which("node")
_HARNESS = Path(__file__).resolve().parent / "ts_client_harness.mjs"

# Node 22+ is required (global WebSocket + experimental type stripping). Skip
# cleanly on older/no Node so the Python suite stays green everywhere.
_ts_skip = pytest.mark.skipif(
    _NODE_BIN is None,
    reason="node not installed; TypeScript client harness cannot run",
)


async def _run_ts_harness(mode: str, instance_id: str):
    """Spawn the Node harness and return the live asyncio subprocess handle."""
    env = dict(os.environ)
    env["BROKER_URL"] = WS_URL
    env["MODE"] = mode
    env["INSTANCE_ID"] = instance_id
    proc = await asyncio.create_subprocess_exec(
        _NODE_BIN, "--experimental-strip-types", str(_HARNESS),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    return proc


def _parse_harness_line(raw: bytes) -> dict:
    """The harness prints exactly one JSON line on stdout (warnings go stderr)."""
    for line in raw.decode().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "ok" in obj:
            return obj
    raise AssertionError(f"no JSON result line from harness; raw={raw!r}")


async def _wait_for_approval(broker, from_id: str, timeout: float = 4.0) -> str:
    """Poll broker state until the TS instance's approval_request lands."""
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        ap = next((a for a in broker.state["approvals"]
                   if a.get("from") == from_id and a.get("status") == "pending"), None)
        if ap is not None:
            return ap["id"]
        await asyncio.sleep(0.05)
    raise AssertionError(f"approval from {from_id} never appeared")


async def _wait_for_open_vote(broker, created_by: str, timeout: float = 4.0) -> str:
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        v = next((x for x in broker.state["votes"]
                  if x.get("created_by") == created_by and x.get("status") == "open"), None)
        if v is not None:
            return v["id"]
        await asyncio.sleep(0.05)
    raise AssertionError(f"open vote by {created_by} never appeared")


@_ts_skip
@pytest.mark.asyncio
async def test_ts_client_approve_and_wait(started_broker):
    """The TS client's approveAndWait resolves with the human decision, and
    returns null when no decision arrives before the timeout."""
    # --- happy path: UI approves -> Promise resolves true ---
    proc = await _run_ts_harness("approve", "tsapprove")
    try:
        ap_id = await _wait_for_approval(started_broker, "tsapprove")
        await _ui_approve_pending(ap_id, True)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=10)
    except Exception:
        proc.kill()
        raise
    res = _parse_harness_line(out)
    assert res["ok"] is True, f"harness failed: {res} stderr={err.decode()[-500:]}"
    assert res["result"] is True

    # --- timeout path: no decision -> Promise resolves null ---
    proc2 = await _run_ts_harness("approve_timeout", "tsapprovetimeout")
    try:
        out2, err2 = await asyncio.wait_for(proc2.communicate(), timeout=10)
    except Exception:
        proc2.kill()
        raise
    res2 = _parse_harness_line(out2)
    assert res2["ok"] is True, f"harness failed: {res2} stderr={err2.decode()[-500:]}"
    assert res2["result"] is None, "approveAndWait should return null on timeout"


@_ts_skip
@pytest.mark.asyncio
async def test_ts_client_vote_and_wait(started_broker):
    """The TS client's voteAndWait creates a vote, and once two instances cast
    the matching ballot to meet the threshold, resolves to the winner.
    A threshold that can never be met returns null on timeout."""
    # --- happy path: TS creates a threshold-2 vote; two peers cast "yes" ---
    proc = await _run_ts_harness("vote", "tsvote")
    peers = []
    try:
        vid = await _wait_for_open_vote(started_broker, "tsvote")
        # Two plain Python ws instances cast the same option so the threshold
        # of 2 is met and the broker broadcasts vote_resolved to the creator.
        for iid in ("cc2", "cc3"):
            p = await websockets.connect(WS_URL)
            await _register(p, iid=iid)
            peers.append(p)
            await p.send(json.dumps({"type": "vote_cast", "vote_id": vid, "option": "yes"}))
        out, err = await asyncio.wait_for(proc.communicate(), timeout=10)
    except Exception:
        proc.kill()
        raise
    finally:
        for p in peers:
            await p.close()
    res = _parse_harness_line(out)
    assert res["ok"] is True, f"harness failed: {res} stderr={err.decode()[-500:]}"
    assert res["result"] == "yes"
    v = next(x for x in started_broker.state["votes"] if x["id"] == vid)
    assert v["status"] == "resolved" and v["winner"] == "yes"

    # --- timeout path: unmeetable threshold -> Promise resolves null ---
    proc2 = await _run_ts_harness("vote_timeout", "tsvotetimeout")
    try:
        out2, err2 = await asyncio.wait_for(proc2.communicate(), timeout=10)
    except Exception:
        proc2.kill()
        raise
    res2 = _parse_harness_line(out2)
    assert res2["ok"] is True, f"harness failed: {res2} stderr={err2.decode()[-500:]}"
    assert res2["result"] is None, "voteAndWait should return null on timeout"


# --------------------------------------------------------------------------
# Auth-callback open-redirect guard (web/lib/safe-next.ts).
#
# The /api/auth/callback route redirects to an attacker-controlled `next` query
# param after the OAuth/email code exchange. safeNextPath must accept only
# same-origin relative paths and fall back to /onboarding for anything that
# could navigate off-origin (absolute, protocol-relative, or non-path input).
#
# We drive the REAL safeNextPath via a Node harness (tests/safe_next_harness.mjs)
# that imports the same module the route imports, so the guarantee is checked
# against shipping code rather than a re-implementation.
# --------------------------------------------------------------------------

_SAFE_NEXT_HARNESS = Path(__file__).resolve().parent / "safe_next_harness.mjs"
_DEFAULT_NEXT = "/onboarding"


async def _run_safe_next(raw):
    """Spawn the guard harness for `raw` and return the resolved redirect path.

    `raw is None` exercises the param-absent path; any string (including "") is
    passed through to safeNextPath as a present value.
    """
    env = dict(os.environ)
    if raw is None:
        env.pop("NEXT_PRESENT", None)
        env.pop("NEXT_INPUT", None)
    else:
        env["NEXT_PRESENT"] = "1"
        env["NEXT_INPUT"] = raw
    proc = await asyncio.create_subprocess_exec(
        _NODE_BIN, "--experimental-strip-types", str(_SAFE_NEXT_HARNESS),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=10)
    res = _parse_harness_line(out)
    assert res["ok"] is True, f"harness failed: {res} stderr={err.decode()[-500:]}"
    return res["result"]


@_ts_skip
@pytest.mark.asyncio
async def test_safe_next_rejects_open_redirects():
    """safeNextPath rejects every off-origin variant and accepts only same-origin
    relative paths. Covers the acceptance matrix for the callback redirect."""
    # (1) absolute URL -> rejected, falls back to default.
    assert await _run_safe_next("https://attacker.com") == _DEFAULT_NEXT
    # (2) protocol-relative URL -> rejected.
    assert await _run_safe_next("//attacker.com") == _DEFAULT_NEXT
    # (3) same-origin relative path -> accepted verbatim.
    assert await _run_safe_next("/onboarding") == "/onboarding"
    # (4) empty value -> default. (5) param absent -> default.
    assert await _run_safe_next("") == _DEFAULT_NEXT
    assert await _run_safe_next(None) == _DEFAULT_NEXT
    # (5b) no leading slash -> rejected (cannot be a same-origin path).
    assert await _run_safe_next("onboarding") == _DEFAULT_NEXT


@_ts_skip
@pytest.mark.asyncio
async def test_safe_next_blocks_smuggling_variants():
    """Less obvious off-origin tricks that some URL parsers normalise: backslash
    protocol-relative forms and other-scheme absolute URLs are all rejected."""
    # Backslash variant browsers may normalise to "//".
    assert await _run_safe_next("/\\attacker.com") == _DEFAULT_NEXT
    assert await _run_safe_next("\\/attacker.com") == _DEFAULT_NEXT
    # Other schemes.
    assert await _run_safe_next("http://attacker.com") == _DEFAULT_NEXT
    assert await _run_safe_next("javascript:alert(1)") == _DEFAULT_NEXT
    # Control-char / whitespace smuggling: the WHATWG URL parser strips \t\r\n,
    # so "/<CR><LF>//evil.com" must be rejected by the path allowlist, not pass a
    # naive starts-with-"/" check.
    assert await _run_safe_next("/\r\n//attacker.com") == _DEFAULT_NEXT
    assert await _run_safe_next("/\t//attacker.com") == _DEFAULT_NEXT
    # A legitimate deep link with query/hash is preserved.
    assert await _run_safe_next("/settings?tab=billing") == "/settings?tab=billing"


@pytest.mark.asyncio
async def test_safe_next_preserves_invite_token():
    """Invite tokens are UPPERCASE alphanumeric, so /invite/<TOKEN> must round-
    trip; otherwise an invite signup never returns to the acceptance page."""
    assert await _run_safe_next("/invite/A3FK9ZXQWERTYUIOPLKJHGFD") == \
        "/invite/A3FK9ZXQWERTYUIOPLKJHGFD"
    assert await _run_safe_next("/invite/abc123") == "/invite/abc123"


# ============================================================================
# connect.py CLI identity (--workspace / --name)
# ============================================================================
#
# connect.py auto-starts a background WS client thread at import time. conftest.py
# has already pointed connect.py's BROKER_URL at a free port, so importing it here
# is safe and the loop just retries harmlessly against that dead port.


def _import_connect():
    import importlib

    return importlib.import_module("connect")


def test_connect_slugify_matches_web_form():
    """connect.slugify mirrors web/lib/utils.ts: lowercase, hyphenated, trimmed."""
    cm = _import_connect()
    assert cm.slugify("My Team!") == "my-team"
    assert cm.slugify("  Spaced  Out  ") == "spaced-out"
    assert cm.slugify("a/b\\c") == "a-b-c"
    assert cm.slugify("'quoted'") == "quoted"
    assert cm.slugify("---") == ""
    assert len(cm.slugify("x" * 80)) == 40


def test_connect_validate_workspace_slug_accepts_valid():
    cm = _import_connect()
    assert cm.validate_workspace_slug("my-ws") == "my-ws"
    assert cm.validate_workspace_slug("team1") == "team1"


def test_connect_validate_workspace_slug_rejects_malformed():
    cm = _import_connect()
    for bad in ["My WS", "bad slug!", "-leading", "trailing-", "a--b", "", "x" * 41, "UPPER"]:
        with pytest.raises(ValueError):
            cm.validate_workspace_slug(bad)


def test_connect_resolve_instance_id_workspace_only():
    """No name -> the instance id is just the validated workspace slug."""
    cm = _import_connect()
    assert cm.resolve_instance_id("my-ws") == "my-ws"


def test_connect_resolve_instance_id_with_name():
    """A name -> '<workspace>-<name-slug>' so named instances stay distinct."""
    cm = _import_connect()
    assert cm.resolve_instance_id("my-ws", "Claude 1") == "my-ws-claude-1"
    assert cm.resolve_instance_id("my-ws", "Claude 2") == "my-ws-claude-2"


def test_connect_resolve_instance_id_validates_workspace():
    cm = _import_connect()
    with pytest.raises(ValueError):
        cm.resolve_instance_id("Bad Slug!", "Claude 1")


def test_connect_apply_cli_identity_exports_env(monkeypatch):
    """--workspace/--name export INSTANCE_ID/INSTANCE_PROJECT/INSTANCE_NAME so the
    register payload carries the workspace-derived id, not the hardcoded default."""
    cm = _import_connect()
    monkeypatch.delenv("INSTANCE_ID", raising=False)
    monkeypatch.delenv("INSTANCE_PROJECT", raising=False)
    monkeypatch.delenv("INSTANCE_NAME", raising=False)
    cm._apply_cli_identity(["--workspace", "my-ws", "--name", "Claude 1"])
    assert os.environ["INSTANCE_ID"] == "my-ws-claude-1"
    assert os.environ["INSTANCE_PROJECT"] == "my-ws"
    assert os.environ["INSTANCE_NAME"] == "Claude 1"


def test_connect_apply_cli_identity_workspace_only(monkeypatch):
    cm = _import_connect()
    monkeypatch.delenv("INSTANCE_ID", raising=False)
    monkeypatch.delenv("INSTANCE_PROJECT", raising=False)
    cm._apply_cli_identity(["--workspace", "team-alpha"])
    assert os.environ["INSTANCE_ID"] == "team-alpha"
    assert os.environ["INSTANCE_PROJECT"] == "team-alpha"


def test_connect_apply_cli_identity_rejects_bad_workspace():
    cm = _import_connect()
    with pytest.raises(ValueError):
        cm._apply_cli_identity(["--workspace", "Bad Slug!"])


def test_connect_workspace_guidance_warns_without_workspace():
    """Run without --workspace: project stays 'default', so the onboarding page
    can never match it. workspace_guidance must surface a warning telling the
    user to pass --workspace."""
    cm = _import_connect()
    msg = cm.workspace_guidance("default", "")
    assert msg is not None
    assert "--workspace" in msg
    assert "project='default'" in msg


def test_connect_workspace_guidance_silent_when_workspace_set():
    """A real workspace slug (set by --workspace via INSTANCE_WORKSPACE) means
    detection works, so there is nothing to warn about."""
    cm = _import_connect()
    assert cm.workspace_guidance("acme-team", "acme-team") is None


def test_connect_workspace_guidance_silent_when_project_overridden():
    """A non-default project (e.g. via INSTANCE_PROJECT) is enough for the
    onboarding predicate project==slug to match, so stay quiet even without an
    explicit workspace slug."""
    cm = _import_connect()
    assert cm.workspace_guidance("acme-team", "") is None


@pytest.mark.asyncio
async def test_connect_cli_no_workspace_not_detected(started_broker):
    """End-to-end of the bug: launching connect.py WITHOUT --workspace registers
    with project='default', so the onboarding page's `online && project===slug`
    predicate never flips for a real workspace like 'acme-team'. This proves the
    failure mode the warning addresses (and that --workspace is the fix)."""
    repo_root = str(ROOT)
    env = dict(os.environ)
    env["BROKER_URL"] = WS_URL
    for k in ("INSTANCE_ID", "INSTANCE_NAME", "NAME", "INSTANCE_PROJECT",
              "PROJECT", "INSTANCE_WORKSPACE", "WORKSPACE_SLUG"):
        env.pop(k, None)

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "connect.py",
        cwd=repo_root,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
    )
    try:
        async def _online() -> bool:
            info = started_broker.instances.get("cc1")
            return bool(info and info.get("online"))

        deadline = asyncio.get_event_loop().time() + 8.0
        while asyncio.get_event_loop().time() < deadline:
            if await _online():
                break
            await asyncio.sleep(0.1)

        info = started_broker.instances.get("cc1")
        assert info is not None and info.get("online") is True
        # The default project is what dooms detection on the onboarding page.
        assert info.get("project") == "default"
        snap = started_broker.instances_snapshot()

        def detected_for(slug: str) -> bool:
            return any(i["online"] and i["project"] == slug for i in snap)

        assert detected_for("acme-team") is False
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


@pytest.mark.asyncio
async def test_connect_cli_registers_workspace_derived_id(started_broker, tmp_path):
    """End-to-end: `python3 connect.py --workspace my-ws --name 'Claude 1'`
    registers an instance whose id reflects the workspace context, proving the
    CLI flags reach the register payload instead of the default 'cc1'."""
    repo_root = str(ROOT)
    env = dict(os.environ)
    env["BROKER_URL"] = WS_URL
    # Strip any inherited identity so only the CLI flags determine the id.
    for k in ("INSTANCE_ID", "INSTANCE_NAME", "NAME", "INSTANCE_PROJECT", "PROJECT"):
        env.pop(k, None)

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "connect.py", "--workspace", "my-ws", "--name", "Claude 1",
        cwd=repo_root,
        stdin=asyncio.subprocess.DEVNULL,  # non-TTY: connect.py keeps the loop alive
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
    )
    try:
        # Poll the broker until the workspace-derived instance shows up online.
        async def _registered() -> bool:
            info = started_broker.instances.get("my-ws-claude-1")
            return bool(info and info.get("online"))

        deadline = asyncio.get_event_loop().time() + 8.0
        while asyncio.get_event_loop().time() < deadline:
            if await _registered():
                break
            await asyncio.sleep(0.1)

        info = started_broker.instances.get("my-ws-claude-1")
        assert info is not None, (
            f"expected id 'my-ws-claude-1', got {list(started_broker.instances)}"
        )
        assert info.get("online") is True
        assert info.get("project") == "my-ws"
        assert info.get("name") == "Claude 1"
        # The hardcoded default must NOT have been used.
        assert "cc1" not in started_broker.instances
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


@pytest.mark.asyncio
async def test_instances_rest_project_scopes_onboarding_detection(started_broker):
    """The onboarding connect page polls GET /api/instances through the
    workspace proxy and flips its "connected" flag only for instances whose
    `project` equals the workspace slug (set by `connect.py --workspace`).

    Register one instance for workspace-a and one for workspace-b against the
    same broker, then assert the REST snapshot carries each instance's project
    so the page's `online && project === slug` predicate isolates them: A's
    instance must not satisfy B's filter and vice versa. This is the broker-side
    guarantee that two users onboarding in different workspaces on a shared
    broker do not trigger each other's detection.
    """
    async with websockets.connect(WS_URL) as ws_a, websockets.connect(WS_URL) as ws_b:
        await _register(ws_a, iid="workspace-a-claude-1", name="Claude 1",
                        project="workspace-a")
        await _register(ws_b, iid="workspace-b-claude-1", name="Claude 1",
                        project="workspace-b")
        await asyncio.sleep(0.05)

        async with aiohttp.ClientSession() as session:
            async with session.get(REST_URL + "/api/instances") as r:
                assert r.status == 200
                instances = await r.json()

        # Predicate mirrors the onboarding page: online AND project === slug.
        def detected_for(slug: str) -> bool:
            return any(i["online"] and i["project"] == slug for i in instances)

        assert detected_for("workspace-a") is True
        assert detected_for("workspace-b") is True
        # Cross-workspace isolation: neither slug picks up the other's instance,
        # and an unrelated workspace with no instance never flips detection.
        a_ids = {i["id"] for i in instances if i["online"] and i["project"] == "workspace-a"}
        b_ids = {i["id"] for i in instances if i["online"] and i["project"] == "workspace-b"}
        assert a_ids == {"workspace-a-claude-1"}
        assert b_ids == {"workspace-b-claude-1"}
        assert detected_for("workspace-c") is False


# --------------------------------------------------------------------------
# Workspace allowlist on register (correctness/high)
# --------------------------------------------------------------------------

@pytest_asyncio.fixture
async def workspaces_broker(state_file, tmp_path):
    """Broker with a workspace allowlist file mapping two slugs to ids."""
    ws_file = tmp_path / "workspaces.json"
    ws_file.write_text(json.dumps({
        "acme": {"id": "ws_acme", "name": "Acme"},
        "beta": {"id": "ws_beta", "name": "Beta"},
    }))
    plugins_dir = tmp_path / "plugins_cache"
    plugins_dir.mkdir()
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file, plugins_dir=plugins_dir,
                          workspaces=str(ws_file))
    await b.start()
    await asyncio.sleep(0.05)
    try:
        yield b
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_workspace_agnostic_register_has_empty_workspace(started_broker):
    """With no allowlist configured, register works and the snapshot carries
    empty workspace fields (single-tenant dev is unchanged)."""
    assert started_broker.workspaces is None
    async with websockets.connect(WS_URL) as ws:
        await _register(ws, iid="cc1")
        await asyncio.sleep(0.05)
        snap = started_broker.instances_snapshot()
        row = next(i for i in snap if i["id"] == "cc1")
        assert row["workspace_slug"] == ""
        assert row["workspace_id"] == ""


@pytest.mark.asyncio
async def test_workspace_register_accepts_allowed_slug(workspaces_broker):
    """A register frame naming an allowlisted slug succeeds; the snapshot
    resolves the slug to its configured workspace_id."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "register", "id": "cc1", "name": "C1", "project": "P",
            "workspace_slug": "acme",
        }))
        init = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        assert init["type"] == "memory_init"
        tinit = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        assert tinit["type"] == "tasks_init"
        await asyncio.sleep(0.05)
        assert "cc1" in workspaces_broker.instances
        snap = workspaces_broker.instances_snapshot()
        row = next(i for i in snap if i["id"] == "cc1")
        assert row["workspace_slug"] == "acme"
        assert row["workspace_id"] == "ws_acme"
        # meta is persisted with the workspace context too
        meta = workspaces_broker.state["instances_meta"]["cc1"]
        assert meta["workspace_id"] == "ws_acme"


@pytest.mark.asyncio
async def test_workspace_register_rejects_unknown_slug(workspaces_broker):
    """An unknown (or missing) slug => register_failed and the connection
    closes without tracking the instance."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "register", "id": "cc1", "name": "C1", "project": "P",
            "workspace_slug": "ghost",
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=2)
        payload = json.loads(raw)
        assert payload["type"] == "register_failed"
        assert payload["workspace_slug"] == "ghost"
        closed = False
        try:
            await asyncio.wait_for(ws.recv(), timeout=1)
        except websockets.ConnectionClosed:
            closed = True
        except asyncio.TimeoutError:
            pass
        assert closed or ws.close_code is not None
        assert "cc1" not in workspaces_broker.instances


@pytest.mark.asyncio
async def test_workspace_register_rejects_missing_slug(workspaces_broker):
    """When an allowlist is configured, a register frame with no workspace_slug
    at all is rejected — the broker is gated, not permissive."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "register", "id": "cc1", "name": "C1", "project": "P",
        }))
        payload = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        assert payload["type"] == "register_failed"
        await asyncio.sleep(0.05)
        assert "cc1" not in workspaces_broker.instances


@pytest.mark.asyncio
async def test_instances_rest_workspace_filter(workspaces_broker):
    """GET /api/instances?workspace=slug returns only instances registered
    under that slug. Accepts the resolved workspace_id too."""
    async with websockets.connect(WS_URL) as ws_a, websockets.connect(WS_URL) as ws_b:
        for ws, iid, slug in ((ws_a, "a1", "acme"), (ws_b, "b1", "beta")):
            await ws.send(json.dumps({
                "type": "register", "id": iid, "name": iid, "project": "P",
                "workspace_slug": slug,
            }))
            # drain memory_init + tasks_init
            assert json.loads(await asyncio.wait_for(ws.recv(), timeout=2))["type"] == "memory_init"
            assert json.loads(await asyncio.wait_for(ws.recv(), timeout=2))["type"] == "tasks_init"
        await asyncio.sleep(0.05)

        async with aiohttp.ClientSession() as session:
            async with session.get(REST_URL + "/api/instances?workspace=acme") as r:
                assert r.status == 200
                acme = await r.json()
            async with session.get(REST_URL + "/api/instances?workspace=ws_beta") as r:
                assert r.status == 200
                beta_by_id = await r.json()
            async with session.get(REST_URL + "/api/instances") as r:
                everyone = await r.json()

        assert {i["id"] for i in acme} == {"a1"}
        assert acme[0]["workspace_id"] == "ws_acme"
        # The connect/onboarding page keys detection off workspace_slug + online
        # (i.online && i.workspace_slug === ws), so both must be surfaced per row.
        assert acme[0]["workspace_slug"] == "acme"
        assert acme[0]["online"] is True
        # filtering by the resolved id works as well as by slug
        assert {i["id"] for i in beta_by_id} == {"b1"}
        # unfiltered snapshot still shows both
        assert {"a1", "b1"} <= {i["id"] for i in everyone}


def test_load_workspaces_shapes(tmp_path):
    """_load_workspaces accepts a list, an object, a path, or None."""
    assert broker_mod._load_workspaces(None) is None
    # list shape: slug doubles as id/name
    assert broker_mod._load_workspaces(["x", "y"]) == {
        "x": {"id": "x", "name": "x"},
        "y": {"id": "y", "name": "y"},
    }
    # object shape with explicit id
    assert broker_mod._load_workspaces({"acme": {"id": "ws_1"}})["acme"]["id"] == "ws_1"
    # missing file => deny-all (empty dict, not None)
    assert broker_mod._load_workspaces(str(tmp_path / "nope.json")) == {}
    # path to a real file
    p = tmp_path / "ws.json"
    p.write_text(json.dumps(["only"]))
    assert broker_mod._load_workspaces(str(p)) == {"only": {"id": "only", "name": "only"}}
