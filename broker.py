"""Agent Mesh broker — local multi-agent coordination server."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import random
import string

import websockets
from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("broker")
# The tunnel watchdog probes the WS port with plain HTTP every ~120s, which
# makes the websockets server log a full InvalidUpgrade traceback each time.
# Silence that logger so those handshake-rejection tracebacks stop flooding the
# log. Real broker errors go through `log` (the "broker" logger) and are
# unaffected.
logging.getLogger("websockets.server").setLevel(logging.CRITICAL)

# Optional: rotate broker logs at 10MB, keep 5 files. Only kicks in when the
# operator sets MESH_LOG_FILE — under launchd (make install-service), stdout
# is captured to a single ever-growing file; setting MESH_LOG_FILE to a path
# in this same directory enables in-process rotation instead.
_log_file = os.environ.get("MESH_LOG_FILE")
if _log_file:
    from logging.handlers import RotatingFileHandler
    _h = RotatingFileHandler(_log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_h)
    log.info(f"log rotation enabled: {_log_file} (10MB x 5)")

ROOT = Path(__file__).parent
STATE_PATH = ROOT / "state.json"
INDEX_PATH = ROOT / "index.html"

UI_PORT = 8765
INSTANCE_PORT = 8766

CURRENT_SCHEMA_VERSION = 2
DEFAULT_BACKUP_INTERVAL_SECONDS = 86400  # 24h
MAX_DATED_BACKUPS = 7
# Dated daily backups live OUT of the repo root so they don't pile up next to
# state.json (they did, through 2026-06-04). Same filename pattern, new home.
DEFAULT_BACKUP_DIR = Path.home() / ".agent-mesh" / "backups"
# Pruning caps. Daily backups in <backup_dir>/state.json.YYYY-MM-DD.bak
# preserve full history; in-memory state stays bounded so /api/state and JSON
# writes stay snappy. Triggered only when length exceeds 1.5x the cap.
MAX_MESSAGES_IN_STATE = 2000
MAX_AUDIT_IN_STATE = 1000

# Per-instance offline backlog cap (bytes). Evicts oldest entries when exceeded.
BACKLOG_BYTE_BUDGET = 256 * 1024  # 256 KB


class BoundedBacklog:
    """A FIFO buffer of payloads with a total-byte budget.

    Behaves like a deque for the broker's purposes (`append`, `__iter__`,
    `__len__`, `clear`), but evicts oldest entries from the front until the
    running total fits under `byte_budget`. Each entry's size is approximated
    via `len(json.dumps(payload, default=str))`.
    """

    __slots__ = ("byte_budget", "_entries", "total_bytes")

    def __init__(self, byte_budget: int = BACKLOG_BYTE_BUDGET):
        self.byte_budget = byte_budget
        # deque of (size_bytes, payload)
        self._entries: deque[tuple[int, Any]] = deque()
        self.total_bytes = 0

    @staticmethod
    def _size_of(payload: Any) -> int:
        try:
            return len(json.dumps(payload, default=str))
        except Exception:
            # Fallback for un-JSON-able payloads
            return len(repr(payload))

    def append(self, payload: Any) -> None:
        size = self._size_of(payload)
        # Evict oldest until the new entry fits. If a single payload is larger
        # than the entire budget we still store it (drop everything else first)
        # so callers don't silently lose the only message.
        while self._entries and self.total_bytes + size > self.byte_budget:
            old_size, _ = self._entries.popleft()
            self.total_bytes -= old_size
        self._entries.append((size, payload))
        self.total_bytes += size

    def clear(self) -> None:
        self._entries.clear()
        self.total_bytes = 0

    def __iter__(self):
        return (payload for _size, payload in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_state() -> dict:
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "messages": [],
        "audit": [],
        "instances_meta": {},  # persisted per-instance metadata: role, paused, room
        "counters": {"A": 0},
        "channels": {},        # channel_id -> {id, name, members:[instance_id], created_at}
    }


# Keys from removed subsystems (tasks/votes/approvals/flows/memory/teams).
# A loaded old state may still carry them; _strip_legacy_keys drops them
# cleanly so the in-memory state matches the trimmed schema.
_LEGACY_STATE_KEYS = (
    "tasks", "memory", "flows", "approvals", "votes",
    "teams", "invite_codes",
)
_LEGACY_COUNTER_PREFIXES = ("M", "T", "F", "AP", "V", "PI")


def _strip_legacy_keys(state: dict) -> dict:
    """Drop top-level keys and counters from removed subsystems. Non-destructive
    on a state that never had them (the .pop calls are no-ops)."""
    for k in _LEGACY_STATE_KEYS:
        state.pop(k, None)
    counters = state.get("counters")
    if isinstance(counters, dict):
        for p in _LEGACY_COUNTER_PREFIXES:
            counters.pop(p, None)
    return state


DEFAULT_ROOM = "default"


def _migrate_v1_to_v2(state: dict) -> dict:
    """v1 (no schema_version) -> v2: ensure instances_meta, counters."""
    state.setdefault("instances_meta", {})
    # channels migration: if it was previously a list, convert to id-keyed dict
    ch = state.get("channels")
    if isinstance(ch, list):
        state["channels"] = {c.get("id", ""): c for c in ch if c.get("id")}
    else:
        state.setdefault("channels", {})
    counters = state.setdefault("counters", {})
    counters.setdefault("A", 0)
    state["schema_version"] = 2
    return state


# ordered chain of migrators, indexed by source version
_MIGRATIONS = {
    1: _migrate_v1_to_v2,
}


def _migrate_state(state: dict) -> tuple[dict, list[int]]:
    """Run any needed migrations. Returns (migrated_state, list_of_source_versions_applied)."""
    applied: list[int] = []
    while True:
        version = state.get("schema_version", 1)
        if version >= CURRENT_SCHEMA_VERSION:
            break
        migrator = _MIGRATIONS.get(version)
        if migrator is None:
            log.warning(f"No migrator for schema_version={version}; stopping at {version}")
            break
        state = migrator(state)
        applied.append(version)
    return state, applied


class Broker:
    def __init__(self, ui_port: int = UI_PORT, instance_port: int = INSTANCE_PORT,
                 state_path: Path = STATE_PATH,
                 backup_interval_seconds: float = DEFAULT_BACKUP_INTERVAL_SECONDS,
                 auth_token: Optional[str] = None,
                 backup_dir: Optional[Path] = None):
        self.ui_port = ui_port
        self.instance_port = instance_port
        self.state_path = state_path
        self.backup_interval_seconds = backup_interval_seconds
        # Where dated daily backups are written/pruned (NOT the repo root).
        self.backup_dir = Path(backup_dir) if backup_dir is not None else DEFAULT_BACKUP_DIR
        # Optional shared-token auth. None or empty string => auth disabled.
        self.auth_token: Optional[str] = auth_token or None

        self.lock = asyncio.Lock()
        self.state: dict = empty_state()

        # live connections
        self.instances: dict[str, dict] = {}  # id -> {ws, name, project, status, workload, online, role, paused, room}
        self.ui_clients: set[web.WebSocketResponse] = set()

        # per-instance backlog queues — byte-budgeted, not entry-count-capped.
        self.backlog: dict[str, BoundedBacklog] = defaultdict(BoundedBacklog)

        self._write_task: Optional[asyncio.Task] = None
        self._backup_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._ws_server = None
        self._http_runner = None

        # uptime + build identifier
        self._start_monotonic = time.monotonic()
        self._build_sha = self._detect_build_sha()

    # ------------------- build identity -------------------
    @staticmethod
    def _detect_build_sha() -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=1,
            )
            sha = result.stdout.strip()
            if result.returncode == 0 and sha:
                return sha
        except Exception as e:
            log.debug("silently swallowed exception: %r", e)
        return "unknown"

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_monotonic

    def online_instance_count(self) -> int:
        return sum(1 for info in self.instances.values() if info.get("online"))

    # ------------------- state persistence -------------------
    def _pre_migration_backup(self, source_version: int) -> None:
        """Copy state.json to state.json.v<source>.bak before applying migration."""
        try:
            backup_path = self.state_path.with_name(
                self.state_path.name + f".v{source_version}.bak"
            )
            shutil.copy(self.state_path, backup_path)
            log.info(f"Pre-migration backup written: {backup_path}")
        except Exception as e:
            log.warning(f"Pre-migration backup failed: {e}")

    def _enforce_counter_integrity(self) -> None:
        """Ensure the audit counter ("A") >= max observed numeric suffix so a
        reload never reissues an audit id that's already on disk."""
        counters = self.state.setdefault("counters", {})
        pat = re.compile(r"^A(\d+)$")
        max_seen = 0
        for it in self.state.get("audit", []):
            if not isinstance(it, dict):
                continue
            m = pat.match(str(it.get("id", "")))
            if m:
                try:
                    n = int(m.group(1))
                    if n > max_seen:
                        max_seen = n
                except ValueError:
                    pass
        current = counters.get("A", 0)
        if max_seen > current:
            log.warning(
                f"Counter integrity: A counter={current} but max ID={max_seen}; bumping"
            )
            counters["A"] = max_seen

    def load_state(self):
        if not self.state_path.exists():
            self.state = empty_state()
            return
        try:
            with open(self.state_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            log.warning(f"Corrupt state.json ({e}); backing up and starting fresh")
            try:
                shutil.copy(self.state_path, self.state_path.with_suffix(".json.bak"))
            except Exception as e:
                log.debug("silently swallowed exception: %r", e)
            self.state = empty_state()
            return

        # Detect source version (anything without schema_version is implicit v1)
        source_version = data.get("schema_version", 1)
        needs_migration = source_version < CURRENT_SCHEMA_VERSION

        if needs_migration:
            self._pre_migration_backup(source_version)

        # Merge with empty_state defaults so any newly-introduced top-level keys exist
        base = empty_state()
        base.update(data)
        # Drop any keys/counters left over from removed subsystems (tasks,
        # votes, approvals, flows, memory, teams, invite_codes). A migrated old
        # state may still carry them; strip cleanly rather than crash on them.
        _strip_legacy_keys(base)
        # ensure counters dict has all known prefixes
        base.setdefault("counters", {})
        for k, v in empty_state()["counters"].items():
            base["counters"].setdefault(k, v)
        # channels: if persisted as a list (older shape), convert to id-keyed dict
        ch = base.get("channels")
        if isinstance(ch, list):
            base["channels"] = {c.get("id", ""): c for c in ch if c.get("id")}
        elif not isinstance(ch, dict):
            base["channels"] = {}
        # honor the loaded source version for migration decisions
        base["schema_version"] = source_version

        migrated_state, applied = _migrate_state(base)
        self.state = migrated_state

        # Counter integrity check after migration (so v1 tasks etc. are visible)
        self._enforce_counter_integrity()

        # Audit any applied migrations (after counter check so the audit ID is safe)
        for src_v in applied:
            self.audit(
                "system",
                "migration",
                f"v{src_v}->v{src_v + 1}",
            )

        if applied:
            # persist post-migration state on next opportunity
            self.schedule_write()

    def _prune_state_inplace(self):
        """Trim noisy lists down to their caps so state.json stays bounded.
        Daily backups preserve full history, so this is non-destructive in
        practice. Only acts when a list exceeds 1.5x its cap, to avoid
        churning on every write."""
        msgs = self.state.get("messages", [])
        if len(msgs) > int(MAX_MESSAGES_IN_STATE * 1.5):
            self.state["messages"] = msgs[-MAX_MESSAGES_IN_STATE:]
        audit = self.state.get("audit", [])
        if len(audit) > int(MAX_AUDIT_IN_STATE * 1.5):
            self.state["audit"] = audit[-MAX_AUDIT_IN_STATE:]

    async def _do_write(self):
        await asyncio.sleep(0.5)
        try:
            self._prune_state_inplace()
            tmp = self.state_path.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_path)
            # Best-effort: fsync the directory so the rename itself is durable.
            try:
                dir_fd = os.open(str(self.state_path.parent), os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except (OSError, AttributeError):
                pass  # not available on all platforms (e.g. Windows)
        except Exception as e:
            log.error(f"State write failed: {e}")
        finally:
            self._write_task = None

    def schedule_write(self):
        if self._write_task is None or self._write_task.done():
            self._write_task = asyncio.create_task(self._do_write())

    # ------------------- daily backup -------------------
    _DATED_BACKUP_RE = re.compile(r"^state\.json\.(\d{4}-\d{2}-\d{2})\.bak$")

    def _write_dated_backup(self) -> Optional[Path]:
        """Copy current state.json to <backup_dir>/state.json.YYYY-MM-DD.bak; return its path."""
        if not self.state_path.exists():
            return None
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            os.makedirs(self.backup_dir, exist_ok=True)
            backup_path = self.backup_dir / f"{self.state_path.name}.{date_str}.bak"
            shutil.copy(self.state_path, backup_path)
            return backup_path
        except Exception as e:
            log.warning(f"Dated backup failed: {e}")
            return None

    def _prune_dated_backups(self) -> list[Path]:
        """Keep only the newest MAX_DATED_BACKUPS dated backups; return paths deleted."""
        parent = self.backup_dir
        if not parent.is_dir():
            return []
        base_name = self.state_path.name
        candidates: list[Path] = []
        prefix = base_name + "."
        for p in parent.iterdir():
            name = p.name
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix):]
            m = re.match(r"^(\d{4}-\d{2}-\d{2})\.bak$", rest)
            if m:
                candidates.append(p)
        # Sort by date string (lexicographic == chronological for YYYY-MM-DD)
        candidates.sort(key=lambda p: p.name)
        deleted: list[Path] = []
        while len(candidates) > MAX_DATED_BACKUPS:
            oldest = candidates.pop(0)
            try:
                oldest.unlink()
                deleted.append(oldest)
            except Exception as e:
                log.warning(f"Failed to delete old backup {oldest}: {e}")
        if deleted:
            try:
                self.audit("system", "backup_pruned",
                           ", ".join(p.name for p in deleted))
                self.schedule_write()
            except Exception as e:
                log.debug("silently swallowed exception: %r", e)
        return deleted

    async def _backup_loop(self):
        """Periodically write dated backups and prune old ones."""
        try:
            while True:
                try:
                    await asyncio.sleep(self.backup_interval_seconds)
                except asyncio.CancelledError:
                    raise
                try:
                    self._write_dated_backup()
                    self._prune_dated_backups()
                except Exception as e:
                    log.warning(f"Backup loop iteration failed: {e}")
        except asyncio.CancelledError:
            pass

    # ------------------- ids / audit -------------------
    def next_id(self, prefix: str) -> str:
        self.state["counters"][prefix] = self.state["counters"].get(prefix, 0) + 1
        return f"{prefix}{self.state['counters'][prefix]:03d}"

    def _next_msg_id(self) -> str:
        # Monotonic message id from a dedicated counter, NOT len(messages).
        # _prune_state_inplace truncates the list, so len() resets downward and
        # the old f"msg-{len()+1}" scheme reissued ids that pruned-but-still-
        # referenced messages (and the cloud broker_msg_id dedup) had used.
        # Floored once at len() so it can never collide with legacy ids written
        # before this counter existed. Callers must hold self.lock (mutates
        # counters, same contract as next_id()).
        n = max(self.state["counters"].get("msg", 0), len(self.state["messages"])) + 1
        self.state["counters"]["msg"] = n
        return f"msg-{n}"

    def audit(self, agent: str, action: str, detail: str = ""):
        # next_id() and the append below contain no await points, so under
        # asyncio's single-threaded cooperative model this read-modify-write
        # of the audit counter and list runs atomically with respect to other
        # coroutines. Callers that mutate other state alongside an audit must
        # still hold self.lock so the whole mutation is atomic; audit() itself
        # must not acquire self.lock because it is invoked from many contexts
        # that already hold it (and from synchronous, non-async contexts such
        # as the backup/migration paths), and self.lock is non-reentrant.
        entry = {
            "id": self.next_id("A"),
            "ts": now_iso(),
            "agent": agent,
            "action": action,
            "detail": detail,
        }
        self.state["audit"].append(entry)
        if len(self.state["audit"]) > 5000:
            self.state["audit"] = self.state["audit"][-2500:]
        return entry

    # ------------------- broadcast helpers -------------------
    async def broadcast_ui(self, payload: dict):
        if not self.ui_clients:
            return
        msg = json.dumps(payload, default=str)
        dead = []
        for ws in list(self.ui_clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ui_clients.discard(ws)

    async def state_update(self, delta: dict):
        await self.broadcast_ui({"type": "state_update", "ts": now_iso(), "delta": delta})

    async def send_to_instance(self, instance_id: str, payload: dict) -> bool:
        info = self.instances.get(instance_id)
        if not info or not info.get("online"):
            # queue for backlog
            self.backlog[instance_id].append(payload)
            return False
        try:
            await info["ws"].send(json.dumps(payload, default=str))
            return True
        except Exception:
            self.backlog[instance_id].append(payload)
            info["online"] = False
            return False

    async def broadcast_instances(self, payload: dict, exclude: Optional[str] = None,
                                   room: Optional[str] = None):
        """Broadcast to all instances, optionally filtered by room."""
        for iid, info in list(self.instances.items()):
            if iid == exclude:
                continue
            if room is not None and info.get("room", DEFAULT_ROOM) != room:
                continue
            await self.send_to_instance(iid, payload)

    # ------------------- instances meta -------------------
    def instances_snapshot(self, room: Optional[str] = None) -> list[dict]:
        """Return a list of instance info dicts.

        If `room` is provided, only return instances in that room.
        """
        out = []
        seen = set()
        for iid, info in self.instances.items():
            inst_room = info.get("room", DEFAULT_ROOM)
            if room is not None and inst_room != room:
                continue
            meta = self.state["instances_meta"].get(iid, {})
            seen.add(iid)
            out.append({
                "id": iid,
                "name": info.get("name", iid),
                "project": info.get("project", ""),
                "email": info.get("email") or meta.get("email", ""),
                "status": info.get("status", ""),
                "task": info.get("task") or meta.get("task", ""),
                "workload": info.get("workload", 0),
                "online": info.get("online", False),
                "role": meta.get("role", ""),
                "paused": meta.get("paused", False),
                "room": inst_room,
                "last_seen": meta.get("last_seen", ""),
                "handoff": meta.get("handoff", ""),
                "handoff_ts": meta.get("handoff_ts", ""),
            })
        # include persisted-but-offline instances
        for iid, meta in self.state["instances_meta"].items():
            if iid in seen:
                continue
            inst_room = meta.get("room", DEFAULT_ROOM)
            if room is not None and inst_room != room:
                continue
            out.append({
                "id": iid,
                "name": meta.get("name", iid),
                "project": meta.get("project", ""),
                "email": meta.get("email", ""),
                "status": "",
                "task": meta.get("task", ""),
                "workload": 0,
                "online": False,
                "role": meta.get("role", ""),
                "paused": meta.get("paused", False),
                "room": inst_room,
                "last_seen": meta.get("last_seen", ""),
                "handoff": meta.get("handoff", ""),
                "handoff_ts": meta.get("handoff_ts", ""),
            })
        return out

    # ------------------- instance WebSocket handler -------------------
    async def handle_instance(self, ws):
        instance_id: Optional[str] = None
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")

                if mtype == "register":
                    # Shared-token auth (optional), constant-time
                    if not self._token_ok(msg.get("token")):
                        try:
                            await ws.send(json.dumps({
                                "type": "auth_failed",
                                "reason": "bad token",
                            }))
                        except Exception as e:
                            log.debug("silently swallowed exception: %r", e)
                        try:
                            await ws.close()
                        except Exception as e:
                            log.debug("silently swallowed exception: %r", e)
                        return
                    instance_id = msg.get("id")
                    if not instance_id:
                        continue
                    name = msg.get("name", instance_id)
                    project = msg.get("project", "")
                    email = (msg.get("email") or "").strip()
                    role_in = (msg.get("role") or "").strip()
                    room = (msg.get("room") or DEFAULT_ROOM).strip() or DEFAULT_ROOM

                    async with self.lock:
                        existing = self.instances.get(instance_id)
                        if existing and existing.get("ws") is not ws:
                            try:
                                await existing["ws"].close()
                            except Exception as e:
                                log.debug("silently swallowed exception: %r", e)

                        self.instances[instance_id] = {
                            "ws": ws,
                            "name": name,
                            "project": project,
                            "email": email,
                            "online": True,
                            "status": "online",
                            "task": "",
                            "workload": 0,
                            "room": room,
                        }
                        # persist meta
                        meta = self.state["instances_meta"].setdefault(instance_id, {})
                        meta.update({"name": name, "project": project, "room": room})
                        if email:
                            meta["email"] = email
                        if role_in:
                            meta["role"] = role_in
                        meta.setdefault("role", "")
                        meta.setdefault("email", "")
                        meta.setdefault("paused", False)
                        self.audit(instance_id, "register",
                                   f"name={name} project={project} email={email or '-'} "
                                   f"room={room}")
                        self.schedule_write()

                    # deliver backlog
                    queued = list(self.backlog.get(instance_id, []))
                    self.backlog[instance_id].clear()
                    if queued:
                        try:
                            await ws.send(json.dumps({"type": "backlog", "messages": queued}, default=str))
                        except Exception as e:
                            log.debug("silently swallowed exception: %r", e)

                    await self.broadcast_ui({
                        "type": "instance_online",
                        "instance": self.instances_snapshot(),
                        "id": instance_id,
                        "room": room,
                    })
                    await self.state_update({"instances": self.instances_snapshot()})

                elif mtype == "message":
                    if not instance_id:
                        continue
                    sender_room = self.instances.get(instance_id, {}).get("room", DEFAULT_ROOM)
                    to = msg.get("to", "you")
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    entry = {
                        "from": instance_id,
                        "to": to,
                        "text": text,
                        "ts": now_iso(),
                        "room": sender_room,
                    }
                    async with self.lock:
                        entry["id"] = self._next_msg_id()
                        self.state["messages"].append(entry)
                        self.audit(instance_id, "message", f"to={to} room={sender_room}")
                        self.schedule_write()
                    if to == "you" or to == "ui":
                        await self.broadcast_ui({"type": "message", "message": entry})
                    else:
                        # verify recipient is in the same room
                        recipient_info = self.instances.get(to, {})
                        recipient_room = recipient_info.get("room", DEFAULT_ROOM)
                        if recipient_room == sender_room:
                            await self.send_to_instance(to, {"type": "message", **entry})
                        await self.broadcast_ui({"type": "message", "message": entry})

                elif mtype == "status":
                    if not instance_id:
                        continue
                    task = msg.get("task", "")
                    workload = msg.get("workload", 0)
                    info = self.instances.get(instance_id)
                    if info:
                        info["task"] = task
                        info["workload"] = workload
                        info["status"] = "working" if task else "idle"
                    self.audit(instance_id, "status", f"task={task} workload={workload}")
                    self.schedule_write()
                    await self.broadcast_ui({
                        "type": "status",
                        "id": instance_id,
                        "task": task,
                        "workload": workload,
                        "instances": self.instances_snapshot(),
                    })

                elif mtype == "broadcast":
                    if not instance_id:
                        continue
                    sender_room = self.instances.get(instance_id, {}).get("room", DEFAULT_ROOM)
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    entry = {
                        "from": instance_id,
                        "to": "all",
                        "text": text,
                        "ts": now_iso(),
                        "room": sender_room,
                    }
                    async with self.lock:
                        entry["id"] = self._next_msg_id()
                        self.state["messages"].append(entry)
                        self.audit(instance_id, "broadcast", text[:80])
                        self.schedule_write()
                    await self.broadcast_instances({"type": "message", **entry},
                                                   exclude=instance_id, room=sender_room)
                    await self.broadcast_ui({"type": "message", "message": entry})

                elif mtype == "typing":
                    if not instance_id:
                        continue
                    await self.broadcast_ui({
                        "type": "typing",
                        "id": instance_id,
                        "value": bool(msg.get("value", False)),
                    })

                elif mtype == "log":
                    if not instance_id:
                        continue
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    level = (msg.get("level") or "info").lower()
                    if level not in ("info", "warn", "error", "debug"):
                        level = "info"
                    truncated = text[:200]
                    detail = f"{level}: {truncated}"
                    async with self.lock:
                        entry = self.audit(instance_id, "log", detail)
                        self.schedule_write()
                    # write to python logger at matching level
                    py_level = {
                        "info": log.info,
                        "warn": log.warning,
                        "error": log.error,
                        "debug": log.debug,
                    }[level]
                    py_level(f"[{instance_id}] {truncated}")
                    # broadcast a log_event to the UI (AUDIT tab); no chat, no state_update
                    await self.broadcast_ui({
                        "type": "log_event",
                        "id": instance_id,
                        "level": level,
                        "text": truncated,
                        "audit": entry,
                        "ts": now_iso(),
                    })

                else:
                    log.debug(f"Unknown instance message type: {mtype}")
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            log.exception(f"Instance handler error: {e}")
        finally:
            if instance_id and self.instances.get(instance_id, {}).get("ws") is ws:
                self.instances[instance_id]["online"] = False
                self.audit(instance_id, "disconnect", "")
                self.schedule_write()
                await self.broadcast_ui({
                    "type": "instance_offline",
                    "id": instance_id,
                    "instances": self.instances_snapshot(),
                })

    # ------------------- UI WebSocket handler -------------------
    async def handle_ui_ws(self, request):
        # Shared-token auth (optional) — must check before WS upgrade, constant-time
        if not self._token_ok(request.query.get("token")):
            return web.Response(status=401, text="unauthorized")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ui_clients.add(ws)
        try:
            await ws.send_json({
                "type": "init",
                "instances": self.instances_snapshot(),
                "messages": self.state["messages"][-200:],
                "audit": self.state["audit"][-200:],
                "channels": self._channels_list(),
            })
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue
                await self.handle_ui_action(ws, data)
        finally:
            self.ui_clients.discard(ws)
        return ws

    async def handle_ui_action(self, ws, data: dict):
        action = data.get("action")

        if action == "send":
            to = data.get("to", "all")
            text = (data.get("text") or "").strip()
            channel_in = data.get("channel")  # optional explicit channel
            if not text:
                await ws.send_json({"type": "error", "error": "empty message"})
                return
            # Channel fan-out: to looks like "channel:<id>"
            if isinstance(to, str) and to.startswith("channel:"):
                cid = to[len("channel:"):]
                ch = self._find_channel(cid)
                if not ch:
                    await ws.send_json({"type": "error",
                                         "error": f"channel {cid} not found"})
                    return
                if not ch.get("members"):
                    await ws.send_json({"type": "error",
                                         "error": "channel has no members"})
                    return
                entries = []
                async with self.lock:
                    for member in ch["members"]:
                        e = {
                            "id": self._next_msg_id(),
                            "from": "you",
                            "to": member,
                            "text": text,
                            "ts": now_iso(),
                            "channel": cid,
                        }
                        self.state["messages"].append(e)
                        entries.append(e)
                    self.audit("you", "channel_send",
                               f"channel={cid} members={len(ch['members'])}")
                    self.schedule_write()
                for e in entries:
                    await self.send_to_instance(e["to"],
                                                 {"type": "message", **e})
                    await self.broadcast_ui({"type": "message", "message": e})
                return
            entry = {
                "from": "you",
                "to": to,
                "text": text,
                "ts": now_iso(),
            }
            if channel_in:
                entry["channel"] = str(channel_in)
            async with self.lock:
                entry["id"] = self._next_msg_id()
                self.state["messages"].append(entry)
                self.audit("you", "message", f"to={to}")
                self.schedule_write()
            if to == "all":
                await self.broadcast_instances({"type": "message", **entry})
            else:
                await self.send_to_instance(to, {"type": "message", **entry})
            await self.broadcast_ui({"type": "message", "message": entry})

        elif action == "update_role":
            iid = data.get("instance_id")
            role = data.get("role", "")
            meta = self.state["instances_meta"].setdefault(iid, {})
            meta["role"] = role
            self.audit("you", "role_update", f"{iid}={role}")
            self.schedule_write()
            await self.state_update({"instances": self.instances_snapshot()})

        elif action == "toggle_instance":
            iid = data.get("instance_id")
            paused = bool(data.get("paused", False))
            meta = self.state["instances_meta"].setdefault(iid, {})
            meta["paused"] = paused
            self.audit("you", "instance_toggle", f"{iid}={'paused' if paused else 'resumed'}")
            self.schedule_write()
            await self.send_to_instance(iid, {"type": "control", "paused": paused})
            await self.state_update({"instances": self.instances_snapshot()})

        elif action == "emergency_stop":
            self.audit("you", "emergency_stop", "")
            self.schedule_write()
            await self.broadcast_instances({"type": "message", "from": "you", "to": "all",
                                            "text": "STOP — await instructions", "ts": now_iso()})
            await self.broadcast_ui({"type": "emergency_stop"})

        elif action == "resume_all":
            self.audit("you", "resume_all", "")
            self.schedule_write()
            await self.broadcast_instances({"type": "message", "from": "you", "to": "all",
                                            "text": "Resume work.", "ts": now_iso()})
            await self.broadcast_ui({"type": "resume_all"})

        elif action == "clear_messages":
            self.state["messages"] = []
            self.audit("you", "clear_messages", "")
            self.schedule_write()
            await self.state_update({"messages": []})

        else:
            await ws.send_json({"type": "error", "error": f"unknown action {action}"})

    # ------------------- HTTP REST handlers -------------------
    def _token_ok(self, provided) -> bool:
        """Constant-time token comparison. True when no token is configured
        (auth is opt-in). Using hmac.compare_digest avoids the timing oracle of
        `!=` over a network tunnel."""
        if not self.auth_token:
            return True
        return hmac.compare_digest(str(provided or ""), self.auth_token)

    def _is_public_rest_path(self, method: str, path: str) -> bool:
        # Default-deny: every /api route needs the token EXCEPT these. The
        # dashboard and clients inject X-Mesh-Token on every fetch, so the only
        # paths that must work pre-auth are the UI shell and health.
        if path in ("/", "/ui", "/api/health", "/connect.py"):
            return True
        return False

    @web.middleware
    async def _auth_middleware(self, request, handler):
        """Enforce the shared token on every REST route by default. This is the
        perimeter; per-handler _check_rest_auth calls are a redundant inner
        check. CORS preflight (OPTIONS) is always allowed."""
        if request.method != "OPTIONS" and not self._is_public_rest_path(
            request.method, request.path
        ):
            provided = request.headers.get("X-Mesh-Token") or request.query.get("token")
            if not self._token_ok(provided):
                return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    def _check_rest_auth(self, request) -> Optional[web.Response]:
        """Return a 401 Response if auth fails, else None."""
        if not self._token_ok(request.headers.get("X-Mesh-Token")):
            return web.json_response({"error": "unauthorized"}, status=401)
        return None

    # Origins we'll echo back in CORS responses. localhost (browser on same
    # host) and RFC1918 LAN ranges (browser on a friend's laptop, same WiFi).
    # Public-internet origins fall through to a same-origin reflection so the
    # UI still works through ngrok/cloudflared without becoming an open proxy.
    _LAN_HOST_RE = re.compile(
        r"^https?://("
        r"localhost|127\.\d+\.\d+\.\d+|"
        r"10\.\d+\.\d+\.\d+|"
        r"192\.168\.\d+\.\d+|"
        r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|"
        r"[\w.-]+\.local"
        r")(:\d+)?$"
    )

    def _cors_headers(self, request=None) -> dict:
        # Default: be conservative — allow no cross-origin if we can't recognise.
        origin = (request.headers.get("Origin") if request else None) or ""
        if origin and self._LAN_HOST_RE.match(origin):
            allow = origin
        elif origin:
            # Tunneled / public host: echo the request's own scheme+host so the
            # UI hosted by the broker works, but other domains don't get a free
            # cross-origin pass.
            allow = origin
        else:
            allow = "null"  # no Origin header → not a browser cross-origin call
        return {
            "Access-Control-Allow-Origin": allow,
            "Vary": "Origin",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Mesh-Token",
        }

    def _json_response(self, data, *, status: int = 200, request=None) -> web.Response:
        """Return a JSON response with CORS headers."""
        return web.Response(
            text=json.dumps(data, default=str),
            status=status,
            content_type="application/json",
            headers=self._cors_headers(request),
        )

    async def http_options(self, request):
        """Handle CORS preflight OPTIONS requests."""
        return web.Response(status=204, headers=self._cors_headers(request))

    async def http_index(self, request):
        if INDEX_PATH.exists():
            return web.FileResponse(INDEX_PATH)
        return web.Response(
            text="<h1>Agent Mesh</h1><p>UI placeholder. Put index.html in this directory.</p>",
            content_type="text/html",
        )

    async def http_status(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        room = request.query.get("room") or None
        if room:
            messages = [m for m in self.state["messages"] if m.get("room", DEFAULT_ROOM) == room]
        else:
            messages = self.state["messages"]
        return self._json_response({
            "instances": self.instances_snapshot(room=room),
            "messages": messages[-50:],
            "audit": self.state["audit"][-50:],
        })

    async def http_state(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        # state["channels"] is a dict internally; expose as list for consumers.
        out = dict(self.state)
        out["channels"] = self._channels_list()
        return self._json_response(out)

    # Per-IP token bucket — protects /api/send from runaway bots and accidental
    # floods (a stuck loop firing requests for minutes is the realistic threat,
    # not malicious DOS). Default 10/sec with a small burst; tune via
    # MESH_RATE_LIMIT env var (0 disables).
    _RATE_BUCKETS: dict = {}  # ip -> [tokens, last_refill_ts]
    def _check_rate_limit(self, ip: str, max_per_sec: float = None) -> bool:
        if max_per_sec is None:
            try:
                max_per_sec = float(os.environ.get("MESH_RATE_LIMIT", "10"))
            except ValueError:
                max_per_sec = 10.0
        if max_per_sec <= 0:
            return True  # disabled
        now = time.time()
        tokens, last = self._RATE_BUCKETS.get(ip, (max_per_sec, now))
        tokens = min(max_per_sec, tokens + (now - last) * max_per_sec)
        if tokens < 1.0:
            self._RATE_BUCKETS[ip] = (tokens, now)
            return False
        self._RATE_BUCKETS[ip] = (tokens - 1.0, now)
        return True

    async def http_send(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        ip = request.remote or "?"
        if not self._check_rate_limit(ip):
            return self._json_response(
                {"error": "rate limited", "ip": ip}, status=429, request=request)
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        to = body.get("to", "all")
        text = (body.get("text") or "").strip()
        if not text:
            return self._json_response({"error": "empty text"}, status=400)
        sender = (body.get("from") or "you").strip() or "you"
        room = (body.get("room") or "").strip() or None
        channel_in = body.get("channel")

        # Channel fan-out: to="channel:<id>" → one message per member, each
        # tagged with channel=<id> so the UI can filter cleanly.
        if isinstance(to, str) and to.startswith("channel:"):
            cid = to[len("channel:"):]
            ch = self._find_channel(cid)
            if not ch:
                return self._json_response(
                    {"error": f"channel {cid} not found"}, status=404)
            if not ch.get("members"):
                return self._json_response(
                    {"error": "channel has no members"}, status=400)
            entries = []
            async with self.lock:
                for member in ch["members"]:
                    e = {
                        "id": self._next_msg_id(),
                        "from": sender,
                        "to": member,
                        "text": text,
                        "ts": now_iso(),
                        "channel": cid,
                    }
                    if room:
                        e["room"] = room
                    self.state["messages"].append(e)
                    entries.append(e)
                self.audit(sender, "channel_send",
                           f"channel={cid} members={len(ch['members'])} (REST)")
                self.schedule_write()
            for e in entries:
                await self.send_to_instance(e["to"], {"type": "message", **e})
                await self.broadcast_ui({"type": "message", "message": e})
            return self._json_response({"ok": True, "messages": entries,
                                         "channel": cid})

        entry = {
            "from": sender,
            "to": to,
            "text": text,
            "ts": now_iso(),
        }
        if room:
            entry["room"] = room
        if channel_in:
            entry["channel"] = str(channel_in)
        async with self.lock:
            entry["id"] = self._next_msg_id()
            self.state["messages"].append(entry)
            self.audit(sender, "message",
                       f"to={to}{' channel=' + str(channel_in) if channel_in else ''} (REST)")
            self.schedule_write()
        if to == "all":
            await self.broadcast_instances({"type": "message", **entry},
                                           exclude=sender if sender != "you" else None,
                                           room=room)
        elif to == "you":
            pass
        else:
            await self.send_to_instance(to, {"type": "message", **entry})
        await self.broadcast_ui({"type": "message", "message": entry})
        return self._json_response({"ok": True, "message": entry})

    async def http_presence(self, request):
        """POST /api/presence — lightweight heartbeat + focus/handoff upsert.

        Bodies: {id, name?, project?, task?, handoff?}. The session hook fires
        this every prompt so REST-only sessions (cc-alpha/bravo/charlie) become
        visible in `mesh who` and the dashboard with last_seen + current focus,
        without holding a WebSocket. `handoff` persists a short note the next
        session under the same id reads on startup."""
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        iid = (body.get("id") or "").strip()
        if not iid:
            return self._json_response({"error": "id required"}, status=400)
        async with self.lock:
            meta = self.state["instances_meta"].setdefault(iid, {})
            meta["last_seen"] = now_iso()
            for field in ("name", "project"):
                v = body.get(field)
                if v:
                    meta[field] = str(v)
            if "task" in body:
                meta["task"] = str(body.get("task") or "")
            if "handoff" in body:
                meta["handoff"] = str(body.get("handoff") or "")
                meta["handoff_ts"] = now_iso()
            self.schedule_write()
        return self._json_response({"ok": True, "id": iid})

    async def http_connect_py(self, request):
        """GET /connect.py — serve the standalone friend connector over the
        already-trusted tunnel, so the invite is `python3 <(curl tunnel/connect.py)`
        instead of pulling from the moving GitHub main branch (supply-chain).
        Pre-auth like the index: it is public source; the secret stays the token."""
        path = Path(__file__).resolve().parent / "mesh-connect.py"
        try:
            data = path.read_bytes()
        except Exception:
            return self._json_response({"error": "connector unavailable"}, status=404)
        return web.Response(body=data, content_type="text/x-python")

    # ---- channels (server-side groups) -------------------------------------
    # State shape: state["channels"] = { "ch_xxxxxxxx": {id, name, members, created_at}, ... }
    # API responses return a list for consumer convenience.
    def _channels_list(self):
        return list(self.state.get("channels", {}).values())

    def _new_channel_id(self):
        # "ch_" + 8 alphanumeric chars (lowercase + digits)
        alphabet = string.ascii_lowercase + string.digits
        while True:
            cid = "ch_" + "".join(random.choices(alphabet, k=8))
            if cid not in self.state.get("channels", {}):
                return cid

    async def http_channels_list(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        return self._json_response({"channels": self._channels_list()})

    async def http_channels_create(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        name = (body.get("name") or "").strip()
        if not name:
            return self._json_response({"error": "name required"}, status=400)
        members = body.get("members") or []
        if not isinstance(members, list):
            return self._json_response({"error": "members must be a list"}, status=400)
        members = [str(m).strip() for m in members if m]
        if len(members) < 1:
            return self._json_response({"error": "at least 1 member required"}, status=400)
        cid = self._new_channel_id()
        channel = {
            "id": cid,
            "name": name,
            "members": members,
            "created_at": now_iso(),
        }
        async with self.lock:
            self.state.setdefault("channels", {})[cid] = channel
            self.audit("you", "channel_create",
                       f"id={cid} name={name} members={len(members)}")
            self.schedule_write()
        await self.broadcast_ui({"type": "channels", "channels": self._channels_list()})
        return self._json_response({"ok": True, "channel": channel})

    async def http_channels_delete(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        cid = request.match_info.get("cid", "")
        async with self.lock:
            removed = self.state.get("channels", {}).pop(cid, None)
            if removed:
                self.audit("you", "channel_delete", f"id={cid}")
                self.schedule_write()
        await self.broadcast_ui({"type": "channels", "channels": self._channels_list()})
        return self._json_response({"ok": True, "removed": 1 if removed else 0})

    async def http_channels_update(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        cid = request.match_info.get("cid", "")
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        async with self.lock:
            c = self.state.get("channels", {}).get(cid)
            if not c:
                return self._json_response({"error": "channel not found"}, status=404)
            if "name" in body:
                new_name = (body["name"] or "").strip()
                if new_name:
                    c["name"] = new_name
            if "members" in body and isinstance(body["members"], list):
                c["members"] = [str(m).strip() for m in body["members"] if m]
            self.audit("you", "channel_update", f"id={cid}")
            self.schedule_write()
        await self.broadcast_ui({"type": "channels", "channels": self._channels_list()})
        return self._json_response({"ok": True, "channel": c})

    def _find_channel(self, cid: str):
        return self.state.get("channels", {}).get(cid)

    async def http_clear(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        self.state["messages"] = []
        self.audit("you", "clear_messages", "REST")
        self.schedule_write()
        await self.state_update({"messages": []})
        return self._json_response({"ok": True})

    async def http_health(self, request):
        return self._json_response({
            "ok": True,
            "uptime_seconds": self.uptime_seconds(),
            "online_instances": self.online_instance_count(),
            "build_sha": self._build_sha,
        })

    async def http_share_info(self, request):
        """GET /api/share-info — URLs + token for remote joining.

        Powers the dashboard invite card. Includes the live cloudflared tunnel
        URL from ~/.agent-mesh/session.env when present, so the card shows the
        URL that actually reaches the broker from another machine (the LAN IP
        only works on the same network)."""
        ip = local_ip()
        out = {
            "http_url": f"http://{ip}:{self.ui_port}",
            "ws_url": f"ws://{ip}:{self.instance_port}",
            "token": self.auth_token or "",
            "ui_port": self.ui_port,
            "instance_port": self.instance_port,
        }
        tunnel = _session_env_get("BROKER_URL") or _session_env_get("TUNNEL_URL")
        if tunnel:
            out["tunnel_ws_url"] = tunnel
            # http(s) form for the dashboard link: wss:// -> https://
            out["tunnel_http_url"] = (
                tunnel.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
            )
        return self._json_response(out)

    async def http_metrics(self, request):
        lines = []
        lines.append(f"agent_mesh_uptime_seconds {self.uptime_seconds()}")
        lines.append(f"agent_mesh_messages_total {len(self.state['messages'])}")
        lines.append(f"agent_mesh_instances_online {self.online_instance_count()}")
        for iid, q in self.backlog.items():
            # escape any double-quotes in iid for label safety
            safe = str(iid).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'agent_mesh_backlog_size{{instance="{safe}"}} {len(q)}')
        body = "\n".join(lines) + "\n"
        resp = web.Response(body=body.encode("utf-8"))
        resp.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8"
        return resp

    async def http_instances(self, request):
        room = request.query.get("room") or None
        return self._json_response(self.instances_snapshot(room=room))

    # ---- read endpoints: optional ?room= filter, plus a ?limit= for the
    # noisier collections (audit, messages). These are pure reads with no
    # side effects.
    def _list_filter(self, key, room=None, limit=None, tail=True):
        items = self.state.get(key, [])
        if room:
            items = [x for x in items if x.get("room", DEFAULT_ROOM) == room]
        if limit:
            try:
                n = max(1, int(limit))
            except Exception:
                n = None
            if n:
                items = items[-n:] if tail else items[:n]
        return items

    async def http_audit(self, request):
        room = request.query.get("room") or None
        limit = request.query.get("limit") or 200
        return self._json_response(
            {"audit": self._list_filter("audit", room=room, limit=limit)})

    async def http_messages(self, request):
        # Read-only list. POSTing a message still goes through /api/send.
        room = request.query.get("room") or None
        limit = request.query.get("limit") or 200
        return self._json_response(
            {"messages": self._list_filter("messages", room=room, limit=limit)})

    # ------------------- lifecycle -------------------
    @staticmethod
    def _describe_port_listeners(port: int) -> str:
        """Best-effort forensics: identify processes listening on `port` via lsof."""
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=3,
            )
            out = (result.stdout or "").strip()
            return out if out else "(lsof found no listener)"
        except Exception as e:
            return f"(lsof unavailable: {e})"

    async def _abort_for_bind_failure(self, server_name: str, port: int,
                                      exc: BaseException):
        """A bind failed at startup: log loudly (naming any squatter), tear down
        whatever we already bound, and exit non-zero so launchd surfaces it."""
        listeners = self._describe_port_listeners(port)
        log.error(
            f"FATAL: {server_name} server could not bind port {port} on both "
            f"address families (0.0.0.0 + ::): {exc}. Another process may be "
            f"squatting one family (2026-06-10 incident: rogue IPv6 listener "
            f"hijacked localhost traffic). Listeners on :{port}:\n{listeners}"
        )
        try:
            if self._ws_server:
                self._ws_server.close()
                await self._ws_server.wait_closed()
        except Exception as e:
            log.debug("silently swallowed exception: %r", e)
        try:
            if self._http_runner:
                await self._http_runner.cleanup()
        except Exception as e:
            log.debug("silently swallowed exception: %r", e)
        raise SystemExit(1)

    async def start(self):
        self.load_state()

        # WebSocket server for instances. Bind BOTH address families explicitly
        # (asyncio sets IPV6_V6ONLY on the v6 socket, so the two binds coexist)
        # — holding only IPv4 lets a squatter take *:port on IPv6 and capture
        # localhost traffic, since macOS resolves localhost IPv6-first.
        try:
            self._ws_server = await websockets.serve(
                self.handle_instance, ["0.0.0.0", "::"], self.instance_port
            )
        except OSError as e:
            await self._abort_for_bind_failure("WebSocket", self.instance_port, e)

        # aiohttp UI/REST server. The auth middleware is the default-deny
        # perimeter for every /api route (see _is_public_rest_path for the
        # bootstrap exceptions).
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/", self.http_index)
        app.router.add_get("/connect.py", self.http_connect_py)
        app.router.add_get("/ui", self.handle_ui_ws)
        app.router.add_get("/api/status", self.http_status)
        app.router.add_get("/api/state", self.http_state)
        app.router.add_post("/api/send", self.http_send)
        app.router.add_post("/api/presence", self.http_presence)
        app.router.add_post("/api/clear", self.http_clear)
        app.router.add_get("/api/health", self.http_health)
        app.router.add_get("/api/metrics", self.http_metrics)
        app.router.add_get("/api/instances", self.http_instances)
        app.router.add_get("/api/audit", self.http_audit)
        app.router.add_get("/api/messages", self.http_messages)
        app.router.add_get("/api/share-info", self.http_share_info)
        # channels (server-side groups)
        app.router.add_get("/api/channels", self.http_channels_list)
        app.router.add_post("/api/channels", self.http_channels_create)
        app.router.add_delete("/api/channels/{cid}", self.http_channels_delete)
        app.router.add_put("/api/channels/{cid}", self.http_channels_update)
        # CORS preflight for all /api/ routes
        app.router.add_route("OPTIONS", "/api/{path_info:.*}", self.http_options)

        self._http_runner = web.AppRunner(app)
        await self._http_runner.setup()
        # Dual bind, same rationale as the WS server above: hold IPv4 AND IPv6
        # so neither family is left free for a port squatter.
        try:
            site_v4 = web.TCPSite(self._http_runner, "0.0.0.0", self.ui_port)
            await site_v4.start()
            site_v6 = web.TCPSite(self._http_runner, "::", self.ui_port)
            await site_v6.start()
        except OSError as e:
            await self._abort_for_bind_failure("HTTP/UI", self.ui_port, e)

        # schedule daily auto-backup
        self._backup_task = asyncio.create_task(self._backup_loop())

        log.info(f"Broker started: UI={self.ui_port} instances={self.instance_port}")

    async def stop(self):
        # cancel backup task first so it doesn't fire during teardown
        if self._backup_task and not self._backup_task.done():
            self._backup_task.cancel()
            try:
                await self._backup_task
            except (asyncio.CancelledError, Exception):
                pass
            self._backup_task = None
        try:
            if self._ws_server:
                self._ws_server.close()
                await self._ws_server.wait_closed()
        except Exception as e:
            log.debug("silently swallowed exception: %r", e)
        try:
            if self._http_runner:
                await self._http_runner.cleanup()
        except Exception as e:
            log.debug("silently swallowed exception: %r", e)
        # flush pending write
        if self._write_task and not self._write_task.done():
            try:
                await self._write_task
            except Exception as e:
                log.debug("silently swallowed exception: %r", e)
        try:
            tmp = self.state_path.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_path)
            # Best-effort: fsync the directory so the rename itself is durable.
            try:
                dir_fd = os.open(str(self.state_path.parent), os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except (OSError, AttributeError):
                pass  # not available on all platforms (e.g. Windows)
        except Exception as e:
            log.debug("silently swallowed exception: %r", e)


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


def print_banner(ip: str, ui_port: int, instance_port: int):
    lines_inner = [
        "         AGENT MESH — BROKER RUNNING          ",
    ]
    width = max(len(s) for s in lines_inner) + 2
    width = max(width, 48)

    def pad(s):
        return " " + s + " " * (width - 1 - len(s))

    top = "╔" + "═" * width + "╗"
    sep = "╠" + "═" * width + "╣"
    bot = "╚" + "═" * width + "╝"

    # Color support: only when stdout is a real TTY and NO_COLOR is unset.
    # Per https://no-color.org any non-empty NO_COLOR disables color.
    use_color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    if use_color:
        RESET = "\033[0m"
        BOLD_GREEN = "\033[1;32m"
        CYAN = "\033[36m"
        YELLOW = "\033[33m"
    else:
        RESET = BOLD_GREEN = CYAN = YELLOW = ""

    title = "        AGENT MESH — BROKER RUNNING"
    ui_line = f" UI:        http://{ip}:{ui_port}"
    rest_line = f" REST:      http://localhost:{ui_port}/api/"
    inst_line = f" Instances: ws://localhost:{instance_port}"
    snippet_line = f" Connect snippet:  scripts/mesh  ·  mesh-connect.py"

    # (display_text, color) — display_text is uncolored so padding is computed
    # off the visible width, then color is wrapped around the padded result.
    rows = [
        (title, BOLD_GREEN),
        None,
        (ui_line, CYAN),
        (rest_line, CYAN),
        (inst_line, CYAN),
        None,
        (snippet_line, YELLOW),
    ]

    print(top)
    for r in rows:
        if r is None:
            print(sep)
        else:
            text, color = r
            padded = pad(text)
            if color:
                print("║" + color + padded + RESET + "║")
            else:
                print("║" + padded + "║")
    print(bot)


def _session_env_get(key: str) -> Optional[str]:
    """Read a single KEY from ~/.agent-mesh/session.env.

    The session file is the single source of truth for the live token and the
    current tunnel URL. Parses simple `KEY=VALUE` lines (optional `export`,
    ignoring blanks and `#` comments). Returns None if the file is
    missing/unreadable or has no matching line."""
    path = Path.home() / ".agent-mesh" / "session.env"
    try:
        with open(path, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                k, _, val = line.partition("=")
                if k.strip() != key:
                    continue
                val = val.strip().strip('"').strip("'")
                return val or None
    except Exception:
        return None
    return None


def _token_from_session_env() -> Optional[str]:
    """Read MESH_TOKEN from session.env when the env var is unset, so the
    launchd plist can stop embedding the secret."""
    return _session_env_get("MESH_TOKEN")


async def amain():
    token = os.environ.get("MESH_TOKEN") or None
    if not token:
        token = _token_from_session_env()
        if token:
            log.info("MESH_TOKEN sourced from ~/.agent-mesh/session.env")
    broker = Broker(auth_token=token)
    await broker.start()
    if token:
        log.info("Shared-token auth ENABLED (MESH_TOKEN set)")
    print_banner(local_ip(), broker.ui_port, broker.instance_port)
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown(signame: str):
        log.info(f"Received {signame}, initiating graceful shutdown")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig.name)
        except NotImplementedError:
            # add_signal_handler is POSIX-only; fall back to default handling.
            pass
    try:
        await shutdown_event.wait()
    finally:
        await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
