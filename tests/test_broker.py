"""Tests for the Agent Mesh broker."""
from __future__ import annotations

import asyncio
import json
import os
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


UI_PORT = 18865
INST_PORT = 18866
WS_URL = f"ws://localhost:{INST_PORT}"
UI_WS_URL = f"ws://localhost:{UI_PORT}/ui"
REST_URL = f"http://localhost:{UI_PORT}"


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "state.json"


@pytest_asyncio.fixture
async def started_broker(state_file):
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT, state_path=state_file)
    await b.start()
    # tiny pause for server sockets to be ready
    await asyncio.sleep(0.05)
    try:
        yield b
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


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
    finally:
        await b.stop()
        await asyncio.sleep(0.05)

    # now create 9 fake dated backup files in the same dir
    fake_dates = [
        "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
        "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
    ]
    # remove any existing dated backups first to make the count deterministic
    prefix = state_file.name + "."
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
