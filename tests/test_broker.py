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


UI_PORT = 28765
INST_PORT = 28766
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
