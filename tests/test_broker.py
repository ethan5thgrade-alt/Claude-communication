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
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file)
    await b.start()
    # tiny pause for server sockets to be ready
    await asyncio.sleep(0.05)
    try:
        yield b
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


async def _register(ws, iid="cc1", name="Claude 1", project="P"):
    """Register an instance. The broker no longer sends memory_init/tasks_init;
    a registered instance only receives a `backlog` frame when it has queued
    messages, so there is nothing to drain on a fresh register."""
    await ws.send(json.dumps({"type": "register", "id": iid, "name": name, "project": project}))
    return None


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
            async with session.post(REST_URL + "/api/send",
                                    json={"to": "all", "text": "persisted"}) as r:
                assert r.status == 200
        await asyncio.sleep(0.7)  # let debounced write flush
    finally:
        await b.stop()
        await asyncio.sleep(0.1)

    # restart
    b2 = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT, state_path=state_file)
    await b2.start()
    await asyncio.sleep(0.05)
    try:
        texts = [m["text"] for m in b2.state["messages"]]
        assert "persisted" in texts
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
        b.state.setdefault("messages", []).append({
            "id": "msg-durable-1",
            "from": "you",
            "to": "all",
            "text": "durable-write-test",
            "ts": broker_mod.now_iso(),
        })
        b.schedule_write()
        # Wait for the 0.5s debounce + fsync to complete.
        await asyncio.sleep(0.7)
        # Read the file back from disk and verify content.
        assert state_file.exists(), "state file should exist after debounced write"
        on_disk = json.loads(state_file.read_text())
        texts = [m["text"] for m in on_disk.get("messages", [])]
        assert "durable-write-test" in texts
    finally:
        await b.stop()
        await asyncio.sleep(0.05)

    # After stop(), the final flush in Broker.stop also goes through fsync.
    # Re-read the file and confirm it's still intact.
    assert state_file.exists()
    on_disk_after_stop = json.loads(state_file.read_text())
    texts_after = [m["text"] for m in on_disk_after_stop.get("messages", [])]
    assert "durable-write-test" in texts_after


@pytest.mark.asyncio
async def test_shutdown_flushes_state(state_file, tmp_path):
    """Stopping the broker (as the SIGTERM handler does) must flush state to disk."""
    ui_port = UI_PORT + 20
    inst_port = INST_PORT + 20
    b = broker_mod.Broker(ui_port=ui_port, instance_port=inst_port,
                          state_path=state_file)
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
        # on reconnect with queued messages, the broker sends a `backlog` frame
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
async def test_migration_v1_to_v2(state_file):
    """A v1-shaped state.json (no schema_version, no instances_meta) should be
    migrated in-place to schema_version=2, and the keys/counters from removed
    subsystems (tasks/votes/approvals/flows/memory/teams) must be dropped
    cleanly rather than crash the loader."""
    v1_state = {
        "messages": [],
        # legacy subsystems still present on an old on-disk state:
        "tasks": [
            {"id": "T001", "title": "old task", "assignee": "cc1",
             "status": "Backlog", "ts": "2025-01-01T00:00:00+00:00"},
        ],
        "memory": [],
        "flows": [],
        "approvals": [],
        "votes": [],
        "teams": {"team-x": {"id": "team-x"}},
        "invite_codes": {"ABC": "team-x"},
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
    assert "counters" in b.state and "A" in b.state["counters"]
    # legacy keys must be gone after load
    for dead in ("tasks", "memory", "flows", "approvals", "votes",
                 "teams", "invite_codes"):
        assert dead not in b.state, f"legacy key {dead} survived migration"
    # legacy counter prefixes must be gone too
    for dead in ("M", "T", "F", "AP", "V", "PI"):
        assert dead not in b.state["counters"]
    # pre-migration backup file exists
    assert pre_backup.exists()
    # audit entry recorded the migration
    assert any(a.get("action") == "migration" for a in b.state["audit"])


@pytest.mark.asyncio
async def test_counter_integrity_after_load(state_file):
    """If state has an A005 audit entry but counters['A']=2, load_state must bump
    counters['A'] >= 5 so reloads never reissue an existing audit id."""
    state = {
        "schema_version": 2,
        "messages": [],
        "audit": [
            {"id": "A005", "ts": "2025-01-01T00:00:00+00:00",
             "agent": "you", "action": "message", "detail": ""},
        ],
        "instances_meta": {},
        "counters": {"A": 2},
    }
    state_file.write_text(json.dumps(state))
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file)
    b.load_state()
    assert b.state["counters"]["A"] >= 5


@pytest.mark.asyncio
async def test_daily_backup_creates_file_and_prunes(state_file, tmp_path):
    """Broker started with short backup interval should write a dated backup
    into backup_dir (NOT next to state.json); prune keeps only the 7 newest."""
    # seed a state file so backup has something to copy
    state_file.write_text(json.dumps(broker_mod.empty_state()))
    backup_dir = tmp_path / "backups"  # deliberately not created: broker must makedirs

    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file,
                          backup_interval_seconds=0.05,
                          backup_dir=backup_dir)
    await b.start()
    try:
        await asyncio.sleep(0.2)
        # at least one dated backup file should now exist, in backup_dir
        prefix = state_file.name + "."
        dated = [
            p for p in backup_dir.iterdir()
            if p.name.startswith(prefix) and p.name.endswith(".bak")
            and len(p.name) - len(prefix) - 4 == 10  # YYYY-MM-DD = 10 chars
        ]
        assert len(dated) >= 1, f"expected dated backup, found: {[p.name for p in backup_dir.iterdir()]}"
        # nothing got written next to state.json
        stray = [
            p for p in state_file.parent.iterdir()
            if p.name.startswith(prefix) and p.name.endswith(".bak")
        ]
        assert stray == [], f"dated backups leaked into state dir: {[p.name for p in stray]}"

        # now create 9 fake dated backup files in the backup dir
        fake_dates = [
            "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
            "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
        ]
        # remove any existing dated backups first to make the count deterministic
        for p in list(backup_dir.iterdir()):
            if p.name.startswith(prefix) and p.name.endswith(".bak"):
                try:
                    p.unlink()
                except Exception:
                    pass
        for d in fake_dates:
            (backup_dir / f"{state_file.name}.{d}.bak").write_text("{}")

        # prune
        b._prune_dated_backups()

        remaining = [
            p for p in backup_dir.iterdir()
            if p.name.startswith(prefix) and p.name.endswith(".bak")
        ]
        assert len(remaining) == 7
        # The two oldest should have been deleted
        remaining_names = sorted(p.name for p in remaining)
        assert all(date in name for date, name in zip(fake_dates[2:], remaining_names))
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_dual_stack_bind_both_families(state_file, tmp_path):
    """Broker must hold BOTH IPv4 and IPv6 on the HTTP and WS ports, so a
    squatter can't grab the family we'd otherwise leave free."""
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT,
                          state_path=state_file,
                          backup_dir=tmp_path / "backups")
    await b.start()
    try:
        await asyncio.sleep(0.05)
        for port in (UI_PORT, INST_PORT):
            for family, host in ((socket.AF_INET, "127.0.0.1"),
                                 (socket.AF_INET6, "::1")):
                s = socket.socket(family, socket.SOCK_STREAM)
                s.settimeout(2)
                try:
                    s.connect((host, port))
                finally:
                    s.close()
    finally:
        await b.stop()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_bind_failure_exits_nonzero_when_family_squatted(state_file, tmp_path):
    """If another process already holds one address family of a broker port,
    start() must abort with SystemExit(1) instead of half-binding."""
    squat_port = _pick_free_port()
    squatter = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        squatter.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        squatter.bind(("::", squat_port))
        squatter.listen(1)

        b = broker_mod.Broker(ui_port=_pick_free_port(), instance_port=squat_port,
                              state_path=state_file,
                              backup_dir=tmp_path / "backups")
        with pytest.raises(SystemExit) as excinfo:
            await b.start()
        assert excinfo.value.code == 1
    finally:
        squatter.close()


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
        # A fresh register with a valid token sends no init frame; the broker
        # simply tracks the instance. (A bad token would send auth_failed.)
        await asyncio.sleep(0.1)
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
    mutating POSTs) must all 401 without the token, while the public allowlist
    (health) stays open."""
    reads = ("/api/instances", "/api/messages", "/api/audit",
             "/api/channels", "/api/share-info")
    async with aiohttp.ClientSession() as session:
        for path in reads:
            async with session.get(REST_URL + path) as r:
                assert r.status == 401, f"{path} must require a token"
            async with session.get(REST_URL + path,
                                   headers={"X-Mesh-Token": "secret"}) as r:
                assert r.status == 200, f"{path} must pass with the token"
        # Mutating POSTs without a token
        async with session.post(REST_URL + "/api/send",
                                json={"to": "all", "text": "x"}) as r:
            assert r.status == 401
        async with session.post(REST_URL + "/api/channels",
                                json={"name": "c", "members": ["cc1"]}) as r:
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
# broadcast_ui frame types. This test pins the broker-side contract that the
# relay depends on so a broker change can't silently break the stream.

# Keep in sync with FORWARDED_TYPES in the SSE route.
SSE_INIT_COLLECTIONS = (
    "channels", "audit", "messages",
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
async def test_http_metrics_prom_format(started_broker):
    async with aiohttp.ClientSession() as session:
        async with session.get(REST_URL + "/api/metrics") as r:
            assert r.status == 200
            ctype = r.headers.get("Content-Type", "")
            assert "text/plain" in ctype
            body = await r.text()
    assert "agent_mesh_uptime_seconds" in body
    assert "agent_mesh_messages_total" in body
    assert "agent_mesh_instances_online" in body
    # each non-empty line should have at least one whitespace-separated value
    for line in body.strip().splitlines():
        assert " " in line


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
    assert "scripts/mesh" in out
    assert "mesh-connect.py" in out


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
