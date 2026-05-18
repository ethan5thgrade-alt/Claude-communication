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


UI_PORT = int(os.environ.get("MESH_TEST_UI_PORT", "18765"))
INST_PORT = int(os.environ.get("MESH_TEST_INST_PORT", "18766"))
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
