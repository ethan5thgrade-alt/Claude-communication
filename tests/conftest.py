"""Shared pytest fixtures + module-load-time setup.

The big thing this does: ensure that no test module imports `connect` (which
fires off a background WS client thread at import time) before we've patched
BROKER_URL to a free port. Without this, `connect.py`'s auto-loop spends the
entire test run failing to connect to `ws://localhost:8766` (where nothing is
listening), and `test_clients.py` can't beat the race.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


# Pin the port pair for test_clients.py's session-scoped broker before any
# test module gets a chance to import connect. test_clients.py reads these
# back via os.environ.
if "MESH_TEST_CLIENTS_UI_PORT" not in os.environ:
    os.environ["MESH_TEST_CLIENTS_UI_PORT"] = str(_pick_free_port())
if "MESH_TEST_CLIENTS_INST_PORT" not in os.environ:
    os.environ["MESH_TEST_CLIENTS_INST_PORT"] = str(_pick_free_port())

# Override connect.py's default BROKER_URL so the background WS loop targets
# our test broker the moment it's spawned.
_clients_inst_port = os.environ["MESH_TEST_CLIENTS_INST_PORT"]
os.environ["BROKER_URL"] = f"ws://localhost:{_clients_inst_port}"
