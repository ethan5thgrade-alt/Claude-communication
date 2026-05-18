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


UI_PORT = 19765
INST_PORT = 19766
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
