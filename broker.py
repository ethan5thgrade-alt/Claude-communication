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

import aiohttp
import websockets
from aiohttp import web, WSMsgType, ClientTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("broker")

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
# Pruning caps. Daily backups in state.json.YYYY-MM-DD.bak preserve full
# history; in-memory state stays bounded so /api/state and JSON writes
# stay snappy. Triggered only when length exceeds 1.5x the cap.
MAX_MESSAGES_IN_STATE = 2000
MAX_AUDIT_IN_STATE = 1000
# mDNS / Zeroconf service type for agent-mesh broker advertisement.
MDNS_SERVICE_TYPE = "_agent-mesh._tcp.local."
DEFAULT_PLUGINS_DIR = Path.home() / ".claude" / "plugins" / "cache"

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
        "tasks": [],
        "memory": [],
        "flows": [],
        "approvals": [],
        "votes": [],
        "audit": [],
        "instances_meta": {},  # persisted per-instance metadata: role, paused, room
        "counters": {"M": 0, "T": 0, "F": 0, "AP": 0, "V": 0, "A": 0, "PI": 0},
        "teams": {},           # team_id -> {id, name, room, invite_code, created_at, members:[]}
        "invite_codes": {},    # invite_code -> team_id
        "channels": {},        # channel_id -> {id, name, members:[instance_id], created_at}
    }


def _generate_invite_code(length: int = 8) -> str:
    """Generate an 8-character alphanumeric invite code (uppercase)."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))

DEFAULT_ROOM = "default"


def _migrate_v1_to_v2(state: dict) -> dict:
    """v1 (no schema_version) -> v2: ensure instances_meta, counters, created_by on tasks."""
    state.setdefault("instances_meta", {})
    # channels migration: if it was previously a list, convert to id-keyed dict
    ch = state.get("channels")
    if isinstance(ch, list):
        state["channels"] = {c.get("id", ""): c for c in ch if c.get("id")}
    else:
        state.setdefault("channels", {})
    counters = state.setdefault("counters", {})
    for prefix, default in {"M": 0, "T": 0, "F": 0, "AP": 0, "V": 0, "A": 0}.items():
        counters.setdefault(prefix, default)
    for t in state.get("tasks", []):
        if "created_by" not in t:
            t["created_by"] = "unknown"
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
                 plugins_dir: Optional[Path] = None):
        self.ui_port = ui_port
        self.instance_port = instance_port
        self.state_path = state_path
        self.backup_interval_seconds = backup_interval_seconds
        # Optional shared-token auth. None or empty string => auth disabled.
        self.auth_token: Optional[str] = auth_token or None
        self.plugins_dir = Path(plugins_dir) if plugins_dir is not None else DEFAULT_PLUGINS_DIR

        self.lock = asyncio.Lock()
        self.state: dict = empty_state()

        # live connections
        self.instances: dict[str, dict] = {}  # id -> {ws, name, project, status, workload, online, role, paused, room}
        self.ui_clients: set[web.WebSocketResponse] = set()

        # broker-side awaitable approvals: ap_id -> Future[bool]
        self._pending_approvals: dict[str, asyncio.Future] = {}

        # per-instance backlog queues — byte-budgeted, not entry-count-capped.
        self.backlog: dict[str, BoundedBacklog] = defaultdict(BoundedBacklog)

        # flow fire tracking: flow_id -> deque of monotonic timestamps
        self._flow_fires: dict[str, deque] = defaultdict(lambda: deque(maxlen=32))

        # plugin catalog (populated at start)
        self._plugin_catalog: dict[str, dict] = {}
        # plugin_invoke request counter
        self.state.setdefault("counters", {}).setdefault("PI", 0)

        self._write_task: Optional[asyncio.Task] = None
        self._backup_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._ws_server = None
        self._http_runner = None

        # mDNS / Zeroconf advertisement (lazy; may be None if zeroconf not installed)
        self._zc = None
        self._zc_info = None

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
        """Scan all entities, ensure counters >= max observed numeric suffix per prefix."""
        # Map from prefix -> list of id-bearing collections
        collections: dict[str, list] = {
            "M": self.state.get("memory", []),
            "T": self.state.get("tasks", []),
            "F": self.state.get("flows", []),
            "AP": self.state.get("approvals", []),
            "V": self.state.get("votes", []),
            "A": self.state.get("audit", []),
        }
        counters = self.state.setdefault("counters", {})
        # Pattern: longest prefix first to avoid AP matching A
        for prefix in sorted(collections.keys(), key=len, reverse=True):
            items = collections[prefix]
            pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
            max_seen = 0
            for it in items:
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
            current = counters.get(prefix, 0)
            if max_seen > current:
                log.warning(
                    f"Counter integrity: {prefix} counter={current} but max ID={max_seen}; bumping"
                )
                counters[prefix] = max_seen

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
        # ensure counters dict has all known prefixes
        for k, v in empty_state()["counters"].items():
            base["counters"].setdefault(k, v)
        # ensure teams/invite_codes dicts exist (added in later versions)
        base.setdefault("teams", {})
        base.setdefault("invite_codes", {})
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
        """Copy current state.json to state.json.YYYY-MM-DD.bak; return its path."""
        if not self.state_path.exists():
            return None
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        backup_path = self.state_path.with_name(
            self.state_path.name + f".{date_str}.bak"
        )
        try:
            shutil.copy(self.state_path, backup_path)
            return backup_path
        except Exception as e:
            log.warning(f"Dated backup failed: {e}")
            return None

    def _prune_dated_backups(self) -> list[Path]:
        """Keep only the newest MAX_DATED_BACKUPS dated backups; return paths deleted."""
        parent = self.state_path.parent
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
            seen.add(iid)
            meta = self.state["instances_meta"].get(iid, {})
            out.append({
                "id": iid,
                "name": info.get("name", iid),
                "project": info.get("project", ""),
                "email": info.get("email") or meta.get("email", ""),
                "status": info.get("status", ""),
                "task": info.get("task", ""),
                "workload": info.get("workload", 0),
                "online": info.get("online", False),
                "role": meta.get("role", ""),
                "paused": meta.get("paused", False),
                "room": inst_room,
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
                "task": "",
                "workload": 0,
                "online": False,
                "role": meta.get("role", ""),
                "paused": meta.get("paused", False),
                "room": inst_room,
            })
        return out

    # ------------------- votes -------------------
    async def _maybe_resolve_vote(self, vote: dict):
        """Check whether `vote` should auto-resolve and, if so, mark it resolved
        and broadcast `vote_resolved` to all instances + the UI."""
        if vote.get("status") != "open":
            return
        ballots: dict = vote.get("ballots") or {}
        options: list = vote.get("options") or []
        threshold = vote.get("threshold")

        # tally
        counts: dict[str, int] = {opt: 0 for opt in options}
        for opt in ballots.values():
            if opt in counts:
                counts[opt] += 1

        winner: Optional[str] = None

        # threshold path
        if isinstance(threshold, int) and threshold > 0:
            # pick the option (if any) whose count >= threshold; tie-break alphabetically
            qualifying = sorted([o for o, c in counts.items() if c >= threshold])
            if qualifying:
                winner = qualifying[0]

        # all-voted path
        vote_room = vote.get("room", DEFAULT_ROOM)
        if winner is None:
            # required voter set = currently-online instances in the vote's room + "you"
            online_ids = {
                iid for iid, info in self.instances.items()
                if info.get("online") and info.get("room", DEFAULT_ROOM) == vote_room
            }
            required = online_ids | {"you"}
            voted = set(ballots.keys())
            if required and required.issubset(voted):
                # tally winner: highest count, alphabetical tie-break
                max_count = max(counts.values()) if counts else 0
                if max_count > 0:
                    tied = sorted([o for o, c in counts.items() if c == max_count])
                    winner = tied[0]
                else:
                    winner = sorted(options)[0] if options else None

        if winner is None:
            return

        async with self.lock:
            vote["status"] = "resolved"
            vote["winner"] = winner
            vote["resolved_at"] = now_iso()
            self.audit("broker", "vote_resolved", f"{vote['id']}={winner}")
            self.schedule_write()

        payload = {
            "type": "vote_resolved",
            "vote_id": vote["id"],
            "winner": winner,
            "vote": vote,
        }
        await self.broadcast_instances(payload, room=vote_room)
        await self.broadcast_ui(payload)

    # ------------------- plugin catalog -------------------
    def _list_subdir_children(self, path: Path) -> list[str]:
        """List direct child names (files + dirs) of a directory, sorted, hidden-skipped."""
        if not path.exists() or not path.is_dir():
            return []
        try:
            return sorted([p.name for p in path.iterdir() if not p.name.startswith(".")])
        except Exception:
            return []

    def _load_plugin_manifest(self, plugin_root: Path) -> dict:
        """Try common manifest locations; return parsed dict or {}."""
        candidates = [
            plugin_root / ".claude-plugin" / "plugin.json",
            plugin_root / "plugin.json",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                try:
                    with open(c, "r") as f:
                        return json.load(f) or {}
                except Exception as e:
                    log.warning(f"Failed to parse manifest {c}: {e}")
                    return {}
        return {}

    def _scan_plugins(self) -> dict[str, dict]:
        """Walk plugins_dir and build catalog keyed by plugin name.

        Layout assumed: <plugins_dir>/<marketplace>/<plugin>/<version>/...
        If multiple versions exist for a plugin we take the last (lex-sorted) one.
        """
        catalog: dict[str, dict] = {}
        root = self.plugins_dir
        if not root.exists() or not root.is_dir():
            return catalog
        try:
            marketplaces = sorted([p for p in root.iterdir() if p.is_dir()])
        except Exception as e:
            log.warning(f"Plugin scan: cannot list {root}: {e}")
            return catalog
        for mkt in marketplaces:
            try:
                plugins = sorted([p for p in mkt.iterdir() if p.is_dir()])
            except Exception:
                continue
            for plug in plugins:
                try:
                    versions = sorted([p for p in plug.iterdir() if p.is_dir()])
                except Exception:
                    continue
                if not versions:
                    continue
                # take the last (highest lex) version
                ver_dir = versions[-1]
                version = ver_dir.name
                manifest = self._load_plugin_manifest(ver_dir)
                skills = self._list_subdir_children(ver_dir / "skills")
                agents = self._list_subdir_children(ver_dir / "agents")
                commands = self._list_subdir_children(ver_dir / "commands")
                pid = manifest.get("name") or plug.name
                catalog[pid] = {
                    "id": pid,
                    "marketplace": mkt.name,
                    "version": version,
                    "path": str(ver_dir),
                    "manifest_data": manifest,
                    "skills": skills,
                    "agents": agents,
                    "commands": commands,
                }
        return catalog

    def _rescan_plugins(self) -> int:
        """Re-build the plugin catalog. Returns count."""
        self._plugin_catalog = self._scan_plugins()
        return len(self._plugin_catalog)

    def _resolve_plugin_tool(self, plugin_id: str, tool: str) -> Optional[tuple[str, str]]:
        """Find a skill/agent/command in a plugin.

        Returns (kind, abspath) where kind is 'skill' | 'agent' | 'command',
        or None if not found.
        """
        info = self._plugin_catalog.get(plugin_id)
        if not info:
            return None
        ver_dir = Path(info["path"])
        # Skill: subdir under skills/, file SKILL.md inside (or just the dir)
        if tool in info.get("skills", []):
            skill_path = ver_dir / "skills" / tool
            inner = skill_path / "SKILL.md"
            return ("skill", str(inner if inner.exists() else skill_path))
        # Agent: file in agents/ (typically NAME.md). tool may be "name" or "name.md"
        for a in info.get("agents", []):
            if a == tool or a == f"{tool}.md" or a.rsplit(".", 1)[0] == tool:
                return ("agent", str(ver_dir / "agents" / a))
        # Command: file in commands/
        for c in info.get("commands", []):
            if c == tool or c == f"{tool}.md" or c.rsplit(".", 1)[0] == tool:
                return ("command", str(ver_dir / "commands" / c))
        return None

    # ------------------- task dep cycle check -------------------
    def has_cycle(self, tasks: list[dict]) -> bool:
        graph = {t["id"]: list(t.get("deps") or []) for t in tasks}
        visiting, visited = set(), set()

        def dfs(node):
            if node in visiting:
                return True
            if node in visited or node not in graph:
                return False
            visiting.add(node)
            for nxt in graph[node]:
                if dfs(nxt):
                    return True
            visiting.discard(node)
            visited.add(node)
            return False

        return any(dfs(n) for n in graph)

    # ------------------- flow execution engine -------------------
    FLOW_RATE_LIMIT = 5  # max fires per window
    FLOW_RATE_WINDOW = 60.0  # seconds

    def _apply_rate_limit(self, flow_id: str) -> bool:
        """Sliding-window rate limit. Returns True if fire is allowed and records it.

        Returns False if rate exceeded (does NOT record)."""
        now = time.monotonic()
        fires = self._flow_fires[flow_id]
        cutoff = now - self.FLOW_RATE_WINDOW
        while fires and fires[0] < cutoff:
            fires.popleft()
        if len(fires) >= self.FLOW_RATE_LIMIT:
            return False
        fires.append(now)
        return True

    def _render_template(self, template: str, entry: dict, match: Optional[re.Match]) -> str:
        """Render template using {from}, {to}, {text}, {match.0}, {match.1}, ..."""
        # build a context dict; use a defaultdict-like that returns "" for missing keys
        ctx: dict[str, Any] = {
            "from": entry.get("from", ""),
            "to": entry.get("to", ""),
            "text": entry.get("text", ""),
        }
        # match groups: {match.0}=whole match, {match.1}=group(1), ...
        match_groups: dict[str, str] = {}
        if match is not None:
            match_groups["0"] = match.group(0)
            for i, g in enumerate(match.groups(), start=1):
                match_groups[str(i)] = g if g is not None else ""

        # Use a custom Formatter-friendly approach: support {match.N} and {field}
        class _Ctx:
            def __getitem__(_self, key):
                if key.startswith("match."):
                    return match_groups.get(key[6:], "")
                return ctx.get(key, "")

        try:
            # str.format_map supports __getitem__ but not nested attrs; use Formatter
            import string
            formatter = string.Formatter()
            out_parts = []
            for literal_text, field_name, format_spec, conversion in formatter.parse(template):
                out_parts.append(literal_text)
                if field_name is None:
                    continue
                if field_name.startswith("match."):
                    val = match_groups.get(field_name[6:], "")
                else:
                    val = ctx.get(field_name, "")
                out_parts.append(str(val))
            return "".join(out_parts)
        except Exception:
            return template

    def _parse_action(self, action: str) -> Optional[tuple[str, dict]]:
        """Parse an action DSL string.

        Returns (kind, params) or None if unparseable.
            send <to> <template...>         -> ("send", {"to": to, "template": ...})
            broadcast <template...>         -> ("broadcast", {"template": ...})
            webhook <url> <template...>     -> ("webhook", {"url": url, "template": ...})
        """
        if not action:
            return None
        s = action.strip()
        if not s:
            return None
        # split into head + rest, keeping rest intact
        parts = s.split(None, 1)
        head = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if head == "send":
            sub = rest.split(None, 1)
            if len(sub) < 2:
                return None
            to, template = sub[0], sub[1]
            return ("send", {"to": to, "template": template})
        if head == "broadcast":
            if not rest:
                return None
            return ("broadcast", {"template": rest})
        if head == "webhook":
            sub = rest.split(None, 1)
            if len(sub) < 2:
                return None
            url, template = sub[0], sub[1]
            return ("webhook", {"url": url, "template": template})
        return None

    async def _post_webhook(self, url: str, body: dict) -> bool:
        """POST JSON to url with 3s timeout, retry once. Audit each attempt."""
        timeout = ClientTimeout(total=3)
        last_err = None
        for attempt in (1, 2):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=body) as resp:
                        ok = 200 <= resp.status < 300
                        self.audit("flow", "webhook_attempt",
                                   f"{url} status={resp.status} attempt={attempt}")
                        if ok:
                            return True
                        last_err = f"status={resp.status}"
            except Exception as e:
                last_err = str(e)
                self.audit("flow", "webhook_attempt",
                           f"{url} error={e} attempt={attempt}")
            if attempt == 1:
                await asyncio.sleep(0)  # yield before retry
        self.audit("flow", "webhook_failed", f"{url} {last_err}")
        return False

    async def _evaluate_flows(self, entry: dict):
        """Evaluate every enabled flow against the persisted message entry."""
        text = entry.get("text") or ""
        # Iterate over a snapshot to be safe with concurrent edits
        for flow in list(self.state.get("flows", [])):
            if not flow.get("enabled", True):
                continue
            trigger = flow.get("trigger") or ""
            if not trigger:
                # Empty trigger = match nothing (per spec)
                continue
            try:
                pattern = re.compile(trigger)
            except re.error:
                continue
            m = pattern.search(text)
            if not m:
                continue
            fid = flow.get("id", "?")
            # rate limit
            if not self._apply_rate_limit(fid):
                self.audit("flow", "flow_throttled",
                           f"{fid} matched {trigger!r}")
                continue
            self.audit("flow", "flow_fire", f"{fid} matched {trigger!r}")
            parsed = self._parse_action(flow.get("action") or "")
            if not parsed:
                continue
            kind, params = parsed
            template = params.get("template", "")
            rendered = self._render_template(template, entry, m)
            if kind == "send":
                to = params["to"]
                message = {
                    "from": "flow",
                    "to": to,
                    "text": rendered,
                    "ts": now_iso(),
                    "flow": fid,
                }
                async with self.lock:
                    message["id"] = self._next_msg_id()
                    self.state["messages"].append(message)
                    self.schedule_write()
                await self.send_to_instance(to, {"type": "message", **message})
                await self.broadcast_ui({"type": "flow_fired", "id": fid,
                                          "to": to, "text": rendered})
            elif kind == "broadcast":
                message = {
                    "from": "flow",
                    "to": "all",
                    "text": rendered,
                    "ts": now_iso(),
                    "flow": fid,
                }
                async with self.lock:
                    message["id"] = self._next_msg_id()
                    self.state["messages"].append(message)
                    self.schedule_write()
                await self.broadcast_instances({"type": "message", **message})
                await self.broadcast_ui({"type": "flow_fired", "id": fid,
                                          "to": "all", "text": rendered})
            elif kind == "webhook":
                url = params["url"]
                body = {"flow": fid, "text": rendered}
                # fire-and-forget so we don't block message handling
                asyncio.create_task(self._post_webhook(url, body))
                await self.broadcast_ui({"type": "flow_fired", "id": fid,
                                          "url": url, "text": rendered})

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
                                   f"name={name} project={project} email={email or '-'} room={room}")
                        self.schedule_write()

                    # send memory init (room-scoped)
                    room_memory = [m for m in self.state["memory"]
                                   if m.get("room", DEFAULT_ROOM) == room]
                    init_payload = {
                        "type": "memory_init",
                        "memory": room_memory,
                        "ts": now_iso(),
                    }
                    try:
                        await ws.send(json.dumps(init_payload, default=str))
                    except Exception as e:
                        log.debug("silently swallowed exception: %r", e)

                    # send tasks init (focus on this instance's tasks in this room)
                    my_tasks = [t for t in self.state["tasks"]
                                if t.get("assignee") == instance_id
                                and t.get("status") not in ("Done", "Cancelled")
                                and t.get("room", DEFAULT_ROOM) == room]
                    try:
                        await ws.send(json.dumps({
                            "type": "tasks_init",
                            "tasks": my_tasks,
                            "ts": now_iso(),
                        }, default=str))
                    except Exception as e:
                        log.debug("silently swallowed exception: %r", e)

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
                    await self._evaluate_flows(entry)

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

                elif mtype == "approval_request":
                    if not instance_id:
                        continue
                    async with self.lock:
                        ap = {
                            "id": self.next_id("AP"),
                            "from": instance_id,
                            "action": msg.get("action", ""),
                            "risk": msg.get("risk", "low"),
                            "detail": msg.get("detail", ""),
                            "status": "pending",
                            "ts": now_iso(),
                        }
                        self.state["approvals"].append(ap)
                        self.audit(instance_id, "approval_request", ap["action"])
                        self.schedule_write()
                        # create awaitable future so server-side callers can await it too
                        loop = asyncio.get_event_loop()
                        self._pending_approvals[ap["id"]] = loop.create_future()
                    # tell the requesting instance the assigned id so it can correlate
                    try:
                        await ws.send(json.dumps({
                            "type": "approval_pending",
                            "id": ap["id"],
                            "action": ap["action"],
                        }, default=str))
                    except Exception as e:
                        log.debug("silently swallowed exception: %r", e)
                    await self.broadcast_ui({"type": "approval_request", "approval": ap})

                elif mtype == "memory_write":
                    if not instance_id:
                        continue
                    sender_room = self.instances.get(instance_id, {}).get("room", DEFAULT_ROOM)
                    async with self.lock:
                        entry = {
                            "id": self.next_id("M"),
                            "key": msg.get("key", ""),
                            "value": msg.get("value", ""),
                            "type": msg.get("mem_type", "contract"),
                            "by": instance_id,
                            "ts": now_iso(),
                            "room": sender_room,
                        }
                        self.state["memory"].append(entry)
                        self.audit(instance_id, "memory_write", entry["key"])
                        self.schedule_write()
                    await self.broadcast_ui({"type": "memory_write", "memory": entry})
                    await self.broadcast_instances({"type": "memory_write", "memory": entry},
                                                   exclude=instance_id, room=sender_room)

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

                elif mtype == "task_create":
                    if not instance_id:
                        continue
                    sender_room = self.instances.get(instance_id, {}).get("room", DEFAULT_ROOM)
                    title = (msg.get("title") or "").strip()
                    if not title:
                        continue
                    assignee = msg.get("assignee", "") or ""
                    priority = msg.get("priority", "normal")
                    deps = msg.get("deps") or []
                    async with self.lock:
                        tid = self.next_id("T")
                        task = {
                            "id": tid,
                            "title": title,
                            "assignee": assignee,
                            "priority": priority,
                            "deps": list(deps),
                            "status": "In Progress" if assignee else "Backlog",
                            "created_by": instance_id,
                            "ts": now_iso(),
                            "room": sender_room,
                        }
                        if self.has_cycle(self.state["tasks"] + [task]):
                            self.state["counters"]["T"] -= 1
                            try:
                                await ws.send(json.dumps({
                                    "type": "error",
                                    "error": "cyclic task dependencies",
                                    "ref": title,
                                }))
                            except Exception as e:
                                log.debug("silently swallowed exception: %r", e)
                            continue
                        self.state["tasks"].append(task)
                        self.audit(instance_id, "task_create", f"{tid} -> {assignee or 'unassigned'}")
                        self.schedule_write()
                    if assignee and assignee != instance_id:
                        await self.send_to_instance(assignee, {
                            "type": "task_assigned", "task": task,
                        })
                    await self.state_update({"tasks": self.state["tasks"]})

                elif mtype == "task_claim":
                    if not instance_id:
                        continue
                    tid = msg.get("id")
                    async with self.lock:
                        t = next((x for x in self.state["tasks"] if x["id"] == tid), None)
                        if not t:
                            continue
                        t["assignee"] = instance_id
                        t["status"] = "In Progress"
                        self.audit(instance_id, "task_claim", tid)
                        self.schedule_write()
                    await self.state_update({"tasks": self.state["tasks"]})

                elif mtype == "task_status":
                    if not instance_id:
                        continue
                    tid = msg.get("id")
                    status = msg.get("status", "")
                    async with self.lock:
                        t = next((x for x in self.state["tasks"] if x["id"] == tid), None)
                        if not t or not status:
                            continue
                        t["status"] = status
                        self.audit(instance_id, "task_status", f"{tid}->{status}")
                        self.schedule_write()
                    await self.state_update({"tasks": self.state["tasks"]})

                elif mtype == "vote_create":
                    if not instance_id:
                        continue
                    question = (msg.get("question") or "").strip()
                    options = msg.get("options") or []
                    if not question or not isinstance(options, list) or len(options) < 2:
                        try:
                            await ws.send(json.dumps({
                                "type": "error",
                                "error": "vote_create requires question and >=2 options",
                            }))
                        except Exception as e:
                            log.debug("silently swallowed exception: %r", e)
                        continue
                    options = [str(o) for o in options]
                    threshold = msg.get("threshold")
                    if threshold is not None:
                        try:
                            threshold = int(threshold)
                        except Exception:
                            threshold = None
                    sender_room = self.instances.get(instance_id, {}).get("room", DEFAULT_ROOM)
                    async with self.lock:
                        vid = self.next_id("V")
                        vote = {
                            "id": vid,
                            "question": question,
                            "options": list(options),
                            "ballots": {},
                            "threshold": threshold,
                            "status": "open",
                            "winner": None,
                            "created_by": instance_id,
                            "ts": now_iso(),
                            "room": sender_room,
                        }
                        self.state["votes"].append(vote)
                        self.audit(instance_id, "vote_create", f"{vid} q={question[:40]}")
                        self.schedule_write()
                    # echo back the new id so the creator can wait on it
                    try:
                        await ws.send(json.dumps({
                            "type": "vote_pending",
                            "vote_id": vid,
                            "question": question,
                            "options": list(options),
                        }, default=str))
                    except Exception as e:
                        log.debug("silently swallowed exception: %r", e)
                    await self.state_update({"votes": self.state["votes"]})
                    # notify other instances in the same room so they can cast
                    await self.broadcast_instances({
                        "type": "vote_open",
                        "vote": vote,
                    }, exclude=instance_id, room=sender_room)

                elif mtype == "vote_cast":
                    if not instance_id:
                        continue
                    vote_id = msg.get("vote_id")
                    option = msg.get("option")
                    async with self.lock:
                        v = next((x for x in self.state["votes"] if x["id"] == vote_id), None)
                        if not v:
                            # unknown id — silent no-op (don't crash anyone)
                            continue
                        if v.get("status") != "open":
                            continue
                        if option not in v.get("options", []):
                            continue
                        v.setdefault("ballots", {})[instance_id] = option
                        self.audit(instance_id, "vote_cast", f"{vote_id}={option}")
                        self.schedule_write()
                    await self._maybe_resolve_vote(v)
                    await self.state_update({"votes": self.state["votes"]})

                elif mtype == "plugin_invoke":
                    if not instance_id:
                        continue
                    plugin_id = (msg.get("plugin") or "").strip()
                    tool = (msg.get("tool") or "").strip()
                    args = msg.get("args") or {}
                    async with self.lock:
                        req_id = self.next_id("PI")
                    info = self._plugin_catalog.get(plugin_id)
                    resolved = self._resolve_plugin_tool(plugin_id, tool) if info else None
                    if info and resolved:
                        kind, abspath = resolved
                        status = "discovered"
                        path = abspath
                        manifest = info.get("manifest_data", {})
                    elif info:
                        # plugin exists but tool not found
                        kind = ""
                        status = "not_found"
                        path = ""
                        manifest = info.get("manifest_data", {})
                    else:
                        kind = ""
                        status = "not_found"
                        path = ""
                        manifest = {}
                    self.audit(instance_id, "plugin_invoke",
                               f"{plugin_id}:{tool} -> {status} ({req_id})")
                    self.schedule_write()
                    result_payload = {
                        "type": "plugin_invoke_result",
                        "request_id": req_id,
                        "plugin": plugin_id,
                        "tool": tool,
                        "kind": kind,
                        "status": status,
                        "path": path,
                        "manifest": manifest,
                        "args": args,
                        "ts": now_iso(),
                    }
                    await self.send_to_instance(instance_id, result_payload)
                    await self.broadcast_ui({"type": "plugin_invoke", "result": result_payload})

                elif mtype == "task_done":
                    if not instance_id:
                        continue
                    tid = msg.get("id")
                    result = (msg.get("result") or "").strip()
                    t = next((x for x in self.state["tasks"] if x["id"] == tid), None)
                    if not t:
                        continue
                    t["status"] = "Done"
                    t["result"] = result
                    t["done_by"] = instance_id
                    t["done_at"] = now_iso()
                    self.audit(instance_id, "task_done", tid)
                    self.schedule_write()
                    # notify the creator if it's a different instance
                    creator = t.get("created_by")
                    if creator and creator != instance_id and creator != "you":
                        await self.send_to_instance(creator, {
                            "type": "task_completed",
                            "task": t,
                        })
                    await self.state_update({"tasks": self.state["tasks"]})

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
                "tasks": self.state["tasks"],
                "memory": self.state["memory"],
                "flows": self.state["flows"],
                "approvals": self.state["approvals"],
                "votes": self.state["votes"],
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
                    await self._evaluate_flows(e)
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
            await self._evaluate_flows(entry)

        elif action == "approve":
            ap_id = data.get("id")
            decision = bool(data.get("decision"))
            ap = next((a for a in self.state["approvals"] if a["id"] == ap_id), None)
            if not ap:
                await ws.send_json({"type": "error", "error": "approval not found"})
                return
            ap["status"] = "approved" if decision else "rejected"
            ap["decided_at"] = now_iso()
            ap["decision"] = decision
            # audit records both the decider ("you") and the requesting instance + verdict
            self.audit("you", "approval_decision",
                       f"{ap_id} requester={ap.get('from','?')} verdict={ap['status']}")
            self.schedule_write()
            await self.send_to_instance(ap["from"], {
                "type": "approval_decision",
                "id": ap_id,
                "decision": decision,
                "action": ap["action"],
            })
            # resolve any server-side awaiter
            fut = self._pending_approvals.pop(ap_id, None)
            if fut is not None and not fut.done():
                fut.set_result(decision)
            await self.state_update({"approvals": self.state["approvals"]})

        elif action == "vote":
            vote_id = data.get("vote_id")
            option = data.get("option")
            v = next((x for x in self.state["votes"] if x["id"] == vote_id), None)
            if not v:
                await ws.send_json({"type": "error", "error": "vote not found"})
                return
            if v.get("status") != "open":
                return
            if option not in v.get("options", []):
                await ws.send_json({"type": "error", "error": "invalid option"})
                return
            v.setdefault("ballots", {})["you"] = option
            self.audit("you", "vote", f"{vote_id}={option}")
            self.schedule_write()
            await self._maybe_resolve_vote(v)
            await self.state_update({"votes": self.state["votes"]})

        elif action == "create_vote":
            question = (data.get("question") or "").strip()
            options = data.get("options") or []
            if not question or not isinstance(options, list) or len(options) < 2:
                await ws.send_json({"type": "error", "error": "create_vote requires question and >=2 options"})
                return
            options = [str(o) for o in options]
            threshold = data.get("threshold")
            if threshold is not None:
                try:
                    threshold = int(threshold)
                except Exception:
                    threshold = None
            room = (data.get("room") or "").strip() or DEFAULT_ROOM
            async with self.lock:
                vid = self.next_id("V")
                vote = {
                    "id": vid,
                    "question": question,
                    "options": list(options),
                    "ballots": {},
                    "threshold": threshold,
                    "status": "open",
                    "winner": None,
                    "created_by": "you",
                    "ts": now_iso(),
                    "room": room,
                }
                self.state["votes"].append(vote)
                self.audit("you", "vote_create", f"{vid} q={question[:40]}")
                self.schedule_write()
            await self.broadcast_instances({"type": "vote_open", "vote": vote}, room=room)
            await self.state_update({"votes": self.state["votes"]})

        elif action == "create_task":
            async with self.lock:
                tid = self.next_id("T")
                task = {
                    "id": tid,
                    "title": data.get("title", ""),
                    "assignee": data.get("assignee", ""),
                    "priority": data.get("priority", "normal"),
                    "deps": data.get("deps", []),
                    "status": "Backlog",
                    "created_by": "you",
                    "ts": now_iso(),
                }
                if self.has_cycle(self.state["tasks"] + [task]):
                    # roll back the counter
                    self.state["counters"]["T"] -= 1
                    await ws.send_json({"type": "error", "error": "cyclic task dependencies"})
                    return
                self.state["tasks"].append(task)
                self.audit("you", "task_create", tid)
                self.schedule_write()
            if task["assignee"]:
                await self.send_to_instance(task["assignee"], {
                    "type": "task_assigned", "task": task,
                })
            await self.state_update({"tasks": self.state["tasks"]})

        elif action == "move_task":
            tid = data.get("id")
            status = data.get("status")
            t = next((x for x in self.state["tasks"] if x["id"] == tid), None)
            if not t:
                await ws.send_json({"type": "error", "error": "task not found"})
                return
            t["status"] = status
            self.audit("you", "task_move", f"{tid}->{status}")
            self.schedule_write()
            await self.state_update({"tasks": self.state["tasks"]})

        elif action == "update_task":
            tid = data.get("id")
            t = next((x for x in self.state["tasks"] if x["id"] == tid), None)
            if not t:
                await ws.send_json({"type": "error", "error": "task not found"})
                return
            new_deps = data.get("deps", t.get("deps", []))
            candidate = dict(t)
            for k, v in data.items():
                if k in ("action", "id"):
                    continue
                candidate[k] = v
            candidate["deps"] = new_deps
            others = [x for x in self.state["tasks"] if x["id"] != tid]
            if self.has_cycle(others + [candidate]):
                await ws.send_json({"type": "error", "error": "cyclic task dependencies"})
                return
            t.update({k: v for k, v in data.items() if k not in ("action", "id")})
            self.audit("you", "task_update", tid)
            self.schedule_write()
            await self.state_update({"tasks": self.state["tasks"]})

        elif action == "delete_task":
            tid = data.get("id")
            before = len(self.state["tasks"])
            self.state["tasks"] = [t for t in self.state["tasks"] if t["id"] != tid]
            if len(self.state["tasks"]) < before:
                self.audit("you", "task_delete", tid)
                self.schedule_write()
                await self.state_update({"tasks": self.state["tasks"]})

        elif action == "memory_write":
            async with self.lock:
                entry = {
                    "id": self.next_id("M"),
                    "key": data.get("key", ""),
                    "value": data.get("value", ""),
                    "type": data.get("mem_type", "contract"),
                    "by": "you",
                    "ts": now_iso(),
                }
                self.state["memory"].append(entry)
                self.audit("you", "memory_write", entry["key"])
                self.schedule_write()
            await self.broadcast_ui({"type": "memory_write", "memory": entry})
            await self.broadcast_instances({"type": "memory_write", "memory": entry})

        elif action == "memory_delete":
            mid = data.get("id")
            self.state["memory"] = [m for m in self.state["memory"] if m["id"] != mid]
            self.audit("you", "memory_delete", mid)
            self.schedule_write()
            await self.state_update({"memory": self.state["memory"]})

        elif action == "create_flow":
            trigger = data.get("trigger", "")
            if trigger:
                try:
                    re.compile(trigger)
                except re.error as e:
                    await ws.send_json({"type": "error",
                                         "error": f"invalid regex in trigger: {e}"})
                    return
            async with self.lock:
                fid = self.next_id("F")
                flow = {
                    "id": fid,
                    "name": data.get("name", ""),
                    "trigger": trigger,
                    "action": data.get("action_desc", ""),
                    "color": data.get("color", "#888"),
                    "enabled": True,
                    "ts": now_iso(),
                }
                self.state["flows"].append(flow)
                self.audit("you", "flow_create", fid)
                self.schedule_write()
            await self.state_update({"flows": self.state["flows"]})

        elif action == "delete_flow":
            fid = data.get("id")
            self.state["flows"] = [f for f in self.state["flows"] if f["id"] != fid]
            self.audit("you", "flow_delete", fid)
            self.schedule_write()
            await self.state_update({"flows": self.state["flows"]})

        elif action == "toggle_flow":
            fid = data.get("id")
            f = next((x for x in self.state["flows"] if x["id"] == fid), None)
            if f:
                f["enabled"] = bool(data.get("enabled", not f.get("enabled", True)))
                self.audit("you", "flow_toggle", f"{fid}={f['enabled']}")
                self.schedule_write()
                await self.state_update({"flows": self.state["flows"]})

        elif action == "fire_flow":
            fid = data.get("id")
            f = next((x for x in self.state["flows"] if x["id"] == fid), None)
            if f:
                self.audit("you", "flow_fire", fid)
                self.schedule_write()
                await self.broadcast_ui({"type": "flow_fired", "id": fid})

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
        # paths that must work pre-auth are the UI shell, health, and the
        # friend-invite bootstrap (resolve an invite code — returns no token —
        # and join a team with that code).
        if path in ("/", "/ui", "/api/health"):
            return True
        if method == "GET" and path.startswith("/api/invite/"):
            return True
        if method == "POST" and re.match(r"^/api/teams/[^/]+/join$", path):
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
            tasks = [t for t in self.state["tasks"] if t.get("room", DEFAULT_ROOM) == room]
            memory = [m for m in self.state["memory"] if m.get("room", DEFAULT_ROOM) == room]
        else:
            messages = self.state["messages"]
            tasks = self.state["tasks"]
            memory = self.state["memory"]
        return self._json_response({
            "instances": self.instances_snapshot(room=room),
            "messages": messages[-50:],
            "tasks": tasks,
            "memory": memory,
            "approvals": self.state["approvals"],
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
                await self._evaluate_flows(e)
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
        await self._evaluate_flows(entry)
        return self._json_response({"ok": True, "message": entry})

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

    async def http_plugins(self, request):
        out = []
        for pid, info in sorted(self._plugin_catalog.items()):
            out.append({
                "id": pid,
                "marketplace": info.get("marketplace", ""),
                "version": info.get("version", ""),
                "skills": len(info.get("skills", [])),
                "agents": len(info.get("agents", [])),
                "commands": len(info.get("commands", [])),
            })
        return web.json_response({"plugins": out})

    async def http_plugin_detail(self, request):
        pid = request.match_info.get("plugin_id", "")
        info = self._plugin_catalog.get(pid)
        if not info:
            return web.json_response({"error": "plugin not found", "id": pid}, status=404)
        return web.json_response({
            "id": pid,
            "marketplace": info.get("marketplace", ""),
            "version": info.get("version", ""),
            "path": info.get("path", ""),
            "manifest": info.get("manifest_data", {}),
            "skills": info.get("skills", []),
            "agents": info.get("agents", []),
            "commands": info.get("commands", []),
        })

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

    async def http_rooms(self, request):
        """GET /api/rooms — list active rooms with instance counts."""
        room_counts: dict[str, int] = {}
        for iid, info in self.instances.items():
            if not info.get("online"):
                continue
            r = info.get("room", DEFAULT_ROOM)
            room_counts[r] = room_counts.get(r, 0) + 1
        rooms = [
            {"name": name, "online_instances": count}
            for name, count in sorted(room_counts.items())
        ]
        # Also include rooms with offline-only instances from meta
        seen_rooms = {r["name"] for r in rooms}
        for iid, meta in self.state["instances_meta"].items():
            r = meta.get("room", DEFAULT_ROOM)
            if r not in seen_rooms:
                seen_rooms.add(r)
                rooms.append({"name": r, "online_instances": 0})
        rooms.sort(key=lambda x: x["name"])
        return self._json_response({"rooms": rooms})

    async def http_share_info(self, request):
        """GET /api/share-info — return URLs and token for remote joining.

        Used by `claude-talk share` to display join instructions.
        """
        ip = local_ip()
        return self._json_response({
            "http_url": f"http://{ip}:{self.ui_port}",
            "ws_url": f"ws://{ip}:{self.instance_port}",
            "token": self.auth_token or "",
            "ui_port": self.ui_port,
            "instance_port": self.instance_port,
        })

    async def http_metrics(self, request):
        lines = []
        lines.append(f"agent_mesh_uptime_seconds {self.uptime_seconds()}")
        lines.append(f"agent_mesh_messages_total {len(self.state['messages'])}")
        lines.append(f"agent_mesh_tasks_total {len(self.state['tasks'])}")
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

    async def http_tasks(self, request):
        room = request.query.get("room") or None
        if room:
            tasks = [t for t in self.state["tasks"] if t.get("room", DEFAULT_ROOM) == room]
        else:
            tasks = self.state["tasks"]
        return self._json_response({"tasks": tasks})

    async def http_memory(self, request):
        room = request.query.get("room") or None
        if room:
            memory = [m for m in self.state["memory"] if m.get("room", DEFAULT_ROOM) == room]
        else:
            memory = self.state["memory"]
        return self._json_response({"memory": memory})

    # ---- read endpoints for primitives advertised in connect.py helpers -----
    # Mirror the http_tasks/http_memory pattern: optional ?room= filter, plus
    # a ?limit= for the noisier collections (audit, messages). These are pure
    # reads with no side effects.
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

    async def http_approvals(self, request):
        room = request.query.get("room") or None
        return self._json_response(
            {"approvals": self._list_filter("approvals", room=room)})

    async def http_votes(self, request):
        room = request.query.get("room") or None
        return self._json_response(
            {"votes": self._list_filter("votes", room=room)})

    async def http_flows(self, request):
        room = request.query.get("room") or None
        return self._json_response(
            {"flows": self._list_filter("flows", room=room)})

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

    async def http_bots(self, request):
        """GET /api/bots — health snapshot of claude-talk-bot processes.

        Reads ~/.agent-mesh-inbox/{id}.seen mtime and {id}.claude.err size.
        A bot whose .seen file hasn't been touched in 5 minutes is likely
        dead (the poll loop touches it on every cycle). This is a passive
        read — no signals, no inspection of /proc.
        """
        import glob, time as _t
        inbox = Path(os.path.expanduser("~/.agent-mesh-inbox"))
        bots = {}
        if inbox.exists():
            for seen_path in inbox.glob("*.seen"):
                bot_id = seen_path.stem
                try:
                    mtime = seen_path.stat().st_mtime
                    age_s = round(_t.time() - mtime)
                except Exception:
                    mtime, age_s = None, None
                try:
                    seen_count = sum(
                        1 for _ in seen_path.open() if _.strip())
                except Exception:
                    seen_count = None
                err_path = inbox / f"{bot_id}.claude.err"
                err_size = err_path.stat().st_size if err_path.exists() else 0
                bots[bot_id] = {
                    "seen_count": seen_count,
                    "seen_age_seconds": age_s,
                    "stale": (age_s is not None and age_s > 300),
                    "claude_err_bytes": err_size,
                }
        return self._json_response({"bots": bots})

    async def http_post_task(self, request):
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        title = (body.get("title") or "").strip()
        if not title:
            return self._json_response({"error": "empty title"}, status=400)
        assignee = body.get("assignee", "") or ""
        priority = body.get("priority", "normal")
        deps = body.get("deps") or []
        room = (body.get("room") or DEFAULT_ROOM).strip() or DEFAULT_ROOM
        async with self.lock:
            tid = self.next_id("T")
            task = {
                "id": tid,
                "title": title,
                "assignee": assignee,
                "priority": priority,
                "deps": list(deps),
                "status": "Backlog",
                "created_by": "you",
                "ts": now_iso(),
                "room": room,
            }
            if self.has_cycle(self.state["tasks"] + [task]):
                self.state["counters"]["T"] -= 1
                return self._json_response({"error": "cyclic task dependencies"}, status=400)
            self.state["tasks"].append(task)
            self.audit("you", "task_create", f"{tid} (REST)")
            self.schedule_write()
        if assignee:
            await self.send_to_instance(assignee, {
                "type": "task_assigned", "task": task,
            })
        await self.state_update({"tasks": self.state["tasks"]})
        return self._json_response({"ok": True, "task": task})

    async def http_post_memory(self, request):
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        key = (body.get("key") or "").strip()
        if not key:
            return self._json_response({"error": "empty key"}, status=400)
        value = body.get("value", "")
        mem_type = body.get("mem_type", "contract")
        room = (body.get("room") or DEFAULT_ROOM).strip() or DEFAULT_ROOM
        async with self.lock:
            entry = {
                "id": self.next_id("M"),
                "key": key,
                "value": value,
                "type": mem_type,
                "by": "you",
                "ts": now_iso(),
                "room": room,
            }
            self.state["memory"].append(entry)
            self.audit("you", "memory_write", f"{key} (REST)")
            self.schedule_write()
        await self.broadcast_ui({"type": "memory_write", "memory": entry})
        await self.broadcast_instances({"type": "memory_write", "memory": entry}, room=room)
        return self._json_response({"ok": True, "memory": entry})

    # ---- approvals / votes / flows: REST counterparts of the WS actions ----
    # Each mirrors the equivalent WS handler so behaviour and audit lines are
    # identical regardless of which transport the client uses.

    async def http_post_approval(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        sender = (body.get("from") or "you").strip() or "you"
        action_text = (body.get("action") or "").strip()
        if not action_text:
            return self._json_response({"error": "empty action"}, status=400)
        async with self.lock:
            ap = {
                "id": self.next_id("AP"),
                "from": sender,
                "action": action_text,
                "risk": body.get("risk", "low"),
                "detail": body.get("detail", ""),
                "status": "pending",
                "ts": now_iso(),
            }
            self.state["approvals"].append(ap)
            self.audit(sender, "approval_request", f"{ap['action']} (REST)")
            self.schedule_write()
        await self.broadcast_ui({"type": "approval_request", "approval": ap})
        return self._json_response({"ok": True, "approval": ap})

    async def http_post_approval_respond(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        ap_id = request.match_info.get("ap_id")
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        decision = bool(body.get("approved", body.get("decision")))
        ap = next((a for a in self.state["approvals"] if a["id"] == ap_id), None)
        if not ap:
            return self._json_response({"error": "approval not found"}, status=404)
        async with self.lock:
            ap["status"] = "approved" if decision else "rejected"
            ap["decided_at"] = now_iso()
            ap["decision"] = decision
            self.audit("you", "approval_decision",
                       f"{ap_id} requester={ap.get('from','?')} verdict={ap['status']} (REST)")
            self.schedule_write()
        # notify the original requester instance if connected via WS
        try:
            await self.send_to_instance(ap["from"], {
                "type": "approval_decision",
                "id": ap_id, "decision": decision, "action": ap["action"],
            })
        except Exception as e:
            log.debug("approval_decision notify failed: %r", e)
        # resolve any server-side awaiter
        fut = self._pending_approvals.pop(ap_id, None)
        if fut is not None and not fut.done():
            fut.set_result(decision)
        await self.broadcast_ui({"type": "approvals", "approvals": self.state["approvals"]})
        return self._json_response({"ok": True, "approval": ap})

    async def http_post_vote(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        question = (body.get("question") or "").strip()
        options = body.get("options") or []
        if not question or not isinstance(options, list) or len(options) < 2:
            return self._json_response(
                {"error": "vote requires question and >=2 options"}, status=400)
        options = [str(o) for o in options]
        threshold = body.get("threshold")
        if threshold is not None:
            try:
                threshold = int(threshold)
            except Exception:
                threshold = None
        created_by = (body.get("from") or "you").strip() or "you"
        room = (body.get("room") or "").strip() or DEFAULT_ROOM
        async with self.lock:
            vid = self.next_id("V")
            vote = {
                "id": vid, "question": question, "options": list(options),
                "ballots": {}, "threshold": threshold, "status": "open",
                "winner": None, "created_by": created_by, "ts": now_iso(),
                "room": room,
            }
            self.state["votes"].append(vote)
            self.audit(created_by, "vote_create", f"{vid} q={question[:40]} (REST)")
            self.schedule_write()
        await self.broadcast_instances({"type": "vote_open", "vote": vote}, room=room)
        await self.broadcast_ui({"type": "votes", "votes": self.state["votes"]})
        return self._json_response({"ok": True, "vote": vote})

    async def http_post_vote_cast(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        vote_id = request.match_info.get("vote_id")
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        voter = (body.get("voter") or body.get("from") or "you").strip() or "you"
        option = body.get("option") or body.get("choice")
        v = next((x for x in self.state["votes"] if x["id"] == vote_id), None)
        if not v:
            return self._json_response({"error": "vote not found"}, status=404)
        if v.get("status") != "open":
            return self._json_response({"error": "vote closed"}, status=400)
        if option not in v.get("options", []):
            return self._json_response({"error": "invalid option"}, status=400)
        async with self.lock:
            v.setdefault("ballots", {})[voter] = option
            self.audit(voter, "vote_cast", f"{vote_id}={option} (REST)")
            self.schedule_write()
        await self._maybe_resolve_vote(v)
        await self.broadcast_ui({"type": "votes", "votes": self.state["votes"]})
        return self._json_response({"ok": True, "vote": v})

    async def http_post_flow(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        name = (body.get("name") or "").strip()
        if not name:
            return self._json_response({"error": "empty name"}, status=400)
        trigger = body.get("trigger", "")
        if trigger:
            try:
                re.compile(trigger)
            except re.error as e:
                return self._json_response(
                    {"error": f"invalid regex in trigger: {e}"}, status=400)
        async with self.lock:
            fid = self.next_id("F")
            flow = {
                "id": fid, "name": name,
                "trigger": trigger,
                "action": body.get("action") or body.get("action_desc", ""),
                "color": body.get("color", "#888"),
                "enabled": bool(body.get("enabled", True)),
                "ts": now_iso(),
            }
            self.state["flows"].append(flow)
            self.audit("you", "flow_create", f"{fid} (REST)")
            self.schedule_write()
        await self.broadcast_ui({"type": "flows", "flows": self.state["flows"]})
        return self._json_response({"ok": True, "flow": flow})

    async def http_delete_flow(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        fid = request.match_info.get("fid")
        before = len(self.state["flows"])
        async with self.lock:
            self.state["flows"] = [f for f in self.state["flows"] if f["id"] != fid]
            removed = before - len(self.state["flows"])
            if removed:
                self.audit("you", "flow_delete", f"{fid} (REST)")
                self.schedule_write()
        await self.broadcast_ui({"type": "flows", "flows": self.state["flows"]})
        return self._json_response({"ok": True, "removed": removed})

    async def http_post_flow_fire(self, request):
        denied = self._check_rest_auth(request)
        if denied is not None:
            return denied
        fid = request.match_info.get("fid")
        f = next((x for x in self.state["flows"] if x["id"] == fid), None)
        if not f:
            return self._json_response({"error": "flow not found"}, status=404)
        async with self.lock:
            self.audit("you", "flow_fire", f"{fid} (REST)")
            self.schedule_write()
        await self.broadcast_ui({"type": "flow_fired", "id": fid})
        return self._json_response({"ok": True, "flow": f})

    # ------------------- team endpoints -------------------
    async def http_teams_create(self, request):
        """POST /api/teams — create a team, returns {team_id, invite_code, invite_url}."""
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        name = (body.get("name") or "").strip()
        if not name:
            return self._json_response({"error": "name is required"}, status=400)
        room = (body.get("room") or name.lower().replace(" ", "-")).strip() or "default"

        # Generate a unique invite code
        async with self.lock:
            for _ in range(20):
                code = _generate_invite_code()
                if code not in self.state["invite_codes"]:
                    break
            team_id = f"team-{code.lower()}"
            team = {
                "id": team_id,
                "name": name,
                "room": room,
                "invite_code": code,
                "created_at": now_iso(),
                "members": [],
            }
            self.state["teams"][team_id] = team
            self.state["invite_codes"][code] = team_id
            self.audit("system", "team_create", f"{team_id} name={name} room={room}")
            self.schedule_write()

        # Build invite URL — try to figure out our public URL from ngrok or share-info
        base_url = request.headers.get("X-Forwarded-Host") or f"http://localhost:{self.ui_port}"
        # If accessed via a forwarded host (ngrok), reconstruct the scheme too
        scheme = request.headers.get("X-Forwarded-Proto", "http")
        if request.headers.get("X-Forwarded-Host"):
            base_url = f"{scheme}://{request.headers['X-Forwarded-Host']}"
        invite_url = f"{base_url}/api/invite/{code}"
        return self._json_response({
            "team_id": team_id,
            "name": name,
            "room": room,
            "invite_code": code,
            "invite_url": invite_url,
        })

    async def http_teams_get(self, request):
        """GET /api/teams/{team_id} — get team info."""
        team_id = request.match_info.get("team_id", "")
        team = self.state["teams"].get(team_id)
        if not team:
            return self._json_response({"error": "team not found"}, status=404)
        return self._json_response(team)

    async def http_teams_join(self, request):
        """POST /api/teams/{team_id}/join — join with invite_code, returns {token, room}."""
        team_id = request.match_info.get("team_id", "")
        team = self.state["teams"].get(team_id)
        if not team:
            return self._json_response({"error": "team not found"}, status=404)
        try:
            body = await request.json()
        except Exception:
            return self._json_response({"error": "invalid json"}, status=400)
        invite_code = (body.get("invite_code") or "").strip().upper()
        if invite_code != team["invite_code"]:
            return self._json_response({"error": "invalid invite code"}, status=403)
        member_id = (body.get("instance_id") or body.get("id") or "").strip()
        member_name = (body.get("name") or member_id).strip()
        if member_id:
            async with self.lock:
                members = team.setdefault("members", [])
                existing = next((m for m in members if m["id"] == member_id), None)
                if not existing:
                    members.append({
                        "id": member_id,
                        "name": member_name,
                        "joined_at": now_iso(),
                    })
                self.audit(member_id or "unknown", "team_join", f"{team_id}")
                self.schedule_write()
        return self._json_response({
            "ok": True,
            "team_id": team_id,
            "room": team["room"],
            "token": self.auth_token or "",
        })

    async def http_invite_resolve(self, request):
        """GET /api/invite/{invite_code} — resolve invite code to team info."""
        code = (request.match_info.get("invite_code") or "").strip().upper()
        team_id = self.state["invite_codes"].get(code)
        if not team_id:
            return self._json_response({"error": "invite code not found"}, status=404)
        team = self.state["teams"].get(team_id)
        if not team:
            return self._json_response({"error": "team not found"}, status=404)
        return self._json_response({
            "team_id": team_id,
            "name": team["name"],
            "room": team["room"],
            "invite_code": code,
            "member_count": len(team.get("members", [])),
        })

    # ------------------- lifecycle -------------------
    async def start(self):
        self.load_state()

        # Scan plugins once at startup
        try:
            count = self._rescan_plugins()
            log.info(f"Plugin catalog: {count} plugins under {self.plugins_dir}")
        except Exception as e:
            log.warning(f"Plugin scan failed: {e}")

        # WebSocket server for instances
        self._ws_server = await websockets.serve(
            self.handle_instance, "0.0.0.0", self.instance_port
        )

        # aiohttp UI/REST server. The auth middleware is the default-deny
        # perimeter for every /api route (see _is_public_rest_path for the
        # bootstrap exceptions).
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/", self.http_index)
        app.router.add_get("/ui", self.handle_ui_ws)
        app.router.add_get("/api/status", self.http_status)
        app.router.add_get("/api/state", self.http_state)
        app.router.add_post("/api/send", self.http_send)
        app.router.add_post("/api/clear", self.http_clear)
        app.router.add_get("/api/health", self.http_health)
        app.router.add_get("/api/metrics", self.http_metrics)
        app.router.add_get("/api/instances", self.http_instances)
        app.router.add_get("/api/tasks", self.http_tasks)
        app.router.add_get("/api/memory", self.http_memory)
        app.router.add_get("/api/approvals", self.http_approvals)
        app.router.add_get("/api/votes", self.http_votes)
        app.router.add_get("/api/flows", self.http_flows)
        app.router.add_get("/api/audit", self.http_audit)
        app.router.add_get("/api/messages", self.http_messages)
        app.router.add_get("/api/bots", self.http_bots)
        app.router.add_post("/api/task", self.http_post_task)
        app.router.add_post("/api/memory", self.http_post_memory)
        # approvals / votes / flows: REST counterparts of the WS actions
        app.router.add_post("/api/approval", self.http_post_approval)
        app.router.add_post("/api/approval/{ap_id}/respond", self.http_post_approval_respond)
        app.router.add_post("/api/vote", self.http_post_vote)
        app.router.add_post("/api/vote/{vote_id}/cast", self.http_post_vote_cast)
        app.router.add_post("/api/flow", self.http_post_flow)
        app.router.add_delete("/api/flow/{fid}", self.http_delete_flow)
        app.router.add_post("/api/flow/{fid}/fire", self.http_post_flow_fire)
        app.router.add_get("/api/plugins", self.http_plugins)
        app.router.add_get("/api/plugins/{plugin_id}", self.http_plugin_detail)
        # New endpoints: rooms and share-info
        app.router.add_get("/api/rooms", self.http_rooms)
        app.router.add_get("/api/share-info", self.http_share_info)
        # channels (server-side groups)
        app.router.add_get("/api/channels", self.http_channels_list)
        app.router.add_post("/api/channels", self.http_channels_create)
        app.router.add_delete("/api/channels/{cid}", self.http_channels_delete)
        app.router.add_put("/api/channels/{cid}", self.http_channels_update)
        # Team / invite endpoints
        app.router.add_post("/api/teams", self.http_teams_create)
        app.router.add_get("/api/teams/{team_id}", self.http_teams_get)
        app.router.add_post("/api/teams/{team_id}/join", self.http_teams_join)
        app.router.add_get("/api/invite/{invite_code}", self.http_invite_resolve)
        # CORS preflight for all /api/ routes
        app.router.add_route("OPTIONS", "/api/{path_info:.*}", self.http_options)

        self._http_runner = web.AppRunner(app)
        await self._http_runner.setup()
        site = web.TCPSite(self._http_runner, "0.0.0.0", self.ui_port)
        await site.start()

        # schedule daily auto-backup
        self._backup_task = asyncio.create_task(self._backup_loop())
        # Advertise on LAN via mDNS/zeroconf so phones / other Macs can auto-discover.
        await self._mdns_register()

        log.info(f"Broker started: UI={self.ui_port} instances={self.instance_port}")

    # ------------------- mDNS / Zeroconf -------------------
    async def _mdns_register(self):
        """Register the broker as an `_agent-mesh._tcp.local.` service.

        Lazy/optional: if zeroconf isn't installed (or registration fails for
        any reason), log a warning and continue — discovery is a nicety, not
        a requirement. Uses AsyncZeroconf so it cooperates with our event loop.
        """
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf
        except Exception as e:
            log.warning(f"zeroconf not available; LAN discovery disabled ({e})")
            return

        try:
            ip = local_ip()
            try:
                addr_bytes = socket.inet_aton(ip)
            except OSError:
                addr_bytes = socket.inet_aton("127.0.0.1")

            try:
                hostname = socket.gethostname().split(".")[0] or "broker"
            except Exception:
                hostname = "broker"

            instance_name = f"Agent-Mesh-{hostname}"
            # Service name must be unique within the service-type label.
            service_name = f"{instance_name}.{MDNS_SERVICE_TYPE}"
            # mDNS server label — must end with .local.
            server = f"{hostname}-agent-mesh.local."

            properties = {
                b"version": b"1.0",
                b"instances": str(len(self.instances)).encode("utf-8"),
            }

            info = ServiceInfo(
                type_=MDNS_SERVICE_TYPE,
                name=service_name,
                addresses=[addr_bytes],
                port=self.ui_port,
                properties=properties,
                server=server,
            )
            azc = AsyncZeroconf()
            await azc.async_register_service(info)
            self._zc = azc
            self._zc_info = info
            log.info(f"mDNS advertised: {service_name} -> {ip}:{self.ui_port}")
        except Exception as e:
            log.warning(f"mDNS registration failed; LAN discovery disabled ({e})")
            self._zc = None
            self._zc_info = None

    async def _mdns_unregister(self):
        azc = self._zc
        info = self._zc_info
        self._zc = None
        self._zc_info = None
        if azc is None:
            return
        try:
            if info is not None:
                await azc.async_unregister_service(info)
        except Exception as e:
            log.debug(f"mDNS unregister error: {e}")
        try:
            await azc.async_close()
        except Exception as e:
            log.debug(f"mDNS close error: {e}")

    async def stop(self):
        # cancel backup task first so it doesn't fire during teardown
        if self._backup_task and not self._backup_task.done():
            self._backup_task.cancel()
            try:
                await self._backup_task
            except (asyncio.CancelledError, Exception):
                pass
            self._backup_task = None
        # Unregister mDNS so we stop advertising before any sockets close.
        try:
            await self._mdns_unregister()
        except Exception as e:
            log.debug("silently swallowed exception: %r", e)
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
    snippet_line = f" Connect snippet:  python connect.py"

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


async def amain():
    token = os.environ.get("MESH_TOKEN") or None
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
