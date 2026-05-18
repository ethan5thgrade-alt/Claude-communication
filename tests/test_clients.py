"""End-to-end tests for connect.py helper functions.

These tests exercise the public sync helpers exposed by connect.py against a
running broker fixture. connect.py uses module-level globals plus a background
asyncio thread, and on `import` it immediately spawns that thread + tries to
connect. To keep test_broker.py's port lifecycle clean, we defer the connect
import until *after* the broker fixture is up — using a session-scoped
fixture that imports the module exactly once with BROKER_URL patched to the
test instance port. The background thread is daemon, so it dies with the
test process.

If the helper layer ever becomes too tangled to test cleanly, the protocol
round-trips are covered by tests/test_broker.py — these tests are the
integration check that connect.py wires through to those protocols
correctly.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
import websockets
import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import broker as broker_mod  # noqa: E402

# Use a module-scoped event loop so the session-scoped broker + connect.py
# import (which spans the whole module's worth of tests) can share one loop.
pytestmark = pytest.mark.asyncio(loop_scope="module")

# batch-10 uses distinct ports from test_broker.py (18765/18766) so the two
# test modules can coexist in a single pytest run without port collisions and
# without test_broker's per-test broker stomping on the long-lived broker
# that this module needs for the connect.py background thread.
UI_PORT = int(os.environ.get("MESH_TEST_CLIENTS_UI_PORT", "18775"))
INST_PORT = int(os.environ.get("MESH_TEST_CLIENTS_INST_PORT", "18776"))
WS_URL = f"ws://localhost:{INST_PORT}"
UI_WS_URL = f"ws://localhost:{UI_PORT}/ui"
REST_URL = f"http://localhost:{UI_PORT}"


# --------------------- broker (session-scoped) ---------------------------
# All client-helper tests share one broker + one connect.py session — the
# background thread in connect.py can't be cleanly stopped between tests, so
# tearing the broker down per-test would leave a zombie reconnect loop racing
# the next fixture for the port. One broker, one connect import.
@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shared_broker(tmp_path_factory):
    state_path = tmp_path_factory.mktemp("clients") / "state.json"
    b = broker_mod.Broker(ui_port=UI_PORT, instance_port=INST_PORT, state_path=state_path)
    await b.start()
    await asyncio.sleep(0.05)
    try:
        yield b
    finally:
        await b.stop()
        await asyncio.sleep(0.2)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def connect_mod(shared_broker):
    """Import connect.py with BROKER_URL/INSTANCE_ID patched to the test port.

    Done lazily (inside a fixture, not at module top-level) so test_broker.py
    doesn't see a leftover background ws client trying to hold port 18766.
    """
    # Patch the module-level constants BEFORE the loop's first connect attempt
    # by injecting them into sys.modules via a small shim. Easiest: import,
    # then patch — _client_loop re-reads BROKER_URL on every retry, so even
    # though the first attempt may target ws://localhost:8766, the next
    # iteration (after exponential backoff) picks up the new URL.
    import connect as cm

    cm.BROKER_URL = WS_URL
    cm.INSTANCE_ID = "cc_helper"
    cm.NAME = "Helper"
    cm.PROJECT = "TEST"

    # Wait for connection
    end = asyncio.get_event_loop().time() + 8.0
    while asyncio.get_event_loop().time() < end:
        if cm._ws_holder.get("connected"):
            break
        await asyncio.sleep(0.1)
    assert cm._ws_holder.get("connected"), "connect.py never connected to test broker"

    yield cm
    # No teardown: the background thread is daemon; it dies with the process.


# --------------------------- helpers -------------------------------------
async def _register_protocol(ws, iid="cc_peer", name="Peer", project="TEST"):
    await ws.send(json.dumps({"type": "register", "id": iid, "name": name, "project": project}))
    init = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    assert init["type"] == "memory_init"
    tinit = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    assert tinit["type"] == "tasks_init"
    return init


async def _recv_until(ws, match_fn, timeout=3.0):
    end = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        payload = json.loads(raw)
        if match_fn(payload):
            return payload


# ------------------------------- tests -----------------------------------
async def test_helper_send_round_trip(connect_mod):
    """`broker_send("hi", to="you")` should appear on the UI ws."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(UI_WS_URL) as ui_ws:
            init = await ui_ws.receive_json(timeout=2)
            assert init["type"] == "init"

            connect_mod.broker_send("hi from helper", to="you")

            async def wait_msg():
                async for raw in ui_ws:
                    if raw.type != aiohttp.WSMsgType.TEXT:
                        continue
                    p = json.loads(raw.data)
                    if (p.get("type") == "message"
                            and p.get("message", {}).get("text") == "hi from helper"):
                        return p
            got = await asyncio.wait_for(wait_msg(), timeout=3)
            assert got["message"]["from"] == "cc_helper"


async def test_helper_task_create_assigns(connect_mod):
    """cc_helper creates a task via the helper; cc_peer receives task_assigned."""
    async with websockets.connect(WS_URL) as peer_ws:
        await _register_protocol(peer_ws, iid="cc_peer")
        await asyncio.sleep(0.05)

        connect_mod.broker_task_create(
            "helper-created task", assignee="cc_peer", priority="high"
        )

        got = await _recv_until(peer_ws, lambda p: p.get("type") == "task_assigned")
        assert got["task"]["title"] == "helper-created task"
        assert got["task"]["assignee"] == "cc_peer"
        assert got["task"]["created_by"] == "cc_helper"


async def test_helper_memory_write(connect_mod):
    """`broker_memory` write should fan out to every other registered instance."""
    async with websockets.connect(WS_URL) as peer_ws:
        await _register_protocol(peer_ws, iid="cc_peer2")
        await asyncio.sleep(0.05)

        connect_mod.broker_memory("CONTRACT_KEY", "{shape: 'v1'}", mem_type="contract")

        got = await _recv_until(peer_ws, lambda p: p.get("type") == "memory_write")
        mem = got.get("memory", {})
        assert mem.get("key") == "CONTRACT_KEY"
        assert mem.get("value") == "{shape: 'v1'}"
        assert mem.get("by") == "cc_helper"


async def test_helper_broadcast(connect_mod):
    """`broker_broadcast` should reach every other connected instance."""
    async with websockets.connect(WS_URL) as peer_ws:
        await _register_protocol(peer_ws, iid="cc_peer3")
        await asyncio.sleep(0.05)

        connect_mod.broker_broadcast("all hands via helper")

        got = await _recv_until(
            peer_ws,
            lambda p: p.get("type") == "message" and p.get("text") == "all hands via helper",
        )
        assert got["from"] == "cc_helper"


# ----------- benchmark (opt-in: only runs if pytest-benchmark is installed) ----
try:
    import pytest_benchmark  # noqa: F401
    _HAS_BENCHMARK = True
except ImportError:
    _HAS_BENCHMARK = False


@pytest.mark.skipif(not _HAS_BENCHMARK, reason="pytest-benchmark not installed")
def test_audit_benchmark(benchmark):
    """Microbenchmark for Broker.audit() — exercise the hot append path."""
    b = broker_mod.Broker()
    b.state = broker_mod.empty_state()

    def run():
        b.audit("cc1", "message", "to=cc2")

    benchmark(run)
    assert len(b.state["audit"]) >= 1
