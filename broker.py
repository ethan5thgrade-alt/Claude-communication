"""Agent Mesh broker — local multi-agent coordination server."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import websockets
from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("broker")

ROOT = Path(__file__).parent
STATE_PATH = ROOT / "state.json"
INDEX_PATH = ROOT / "index.html"

UI_PORT = 8765
INSTANCE_PORT = 8766

CURRENT_SCHEMA_VERSION = 2
DEFAULT_BACKUP_INTERVAL_SECONDS = 86400  # 24h
MAX_DATED_BACKUPS = 7


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
        "instances_meta": {},  # persisted per-instance metadata: role, paused
        "counters": {"M": 0, "T": 0, "F": 0, "AP": 0, "V": 0, "A": 0},
    }


def _migrate_v1_to_v2(state: dict) -> dict:
    """v1 (no schema_version) -> v2: ensure instances_meta, counters, created_by on tasks."""
    state.setdefault("instances_meta", {})
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
                 backup_interval_seconds: float = DEFAULT_BACKUP_INTERVAL_SECONDS):
        self.ui_port = ui_port
        self.instance_port = instance_port
        self.state_path = state_path
        self.backup_interval_seconds = backup_interval_seconds

        self.lock = asyncio.Lock()
        self.state: dict = empty_state()

        # live connections
        self.instances: dict[str, dict] = {}  # id -> {ws, name, project, status, workload, online, role, paused}
        self.ui_clients: set[web.WebSocketResponse] = set()

        # broker-side awaitable approvals: ap_id -> Future[bool]
        self._pending_approvals: dict[str, asyncio.Future] = {}

        # per-instance backlog queues
        self.backlog: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

        self._write_task: Optional[asyncio.Task] = None
        self._backup_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._ws_server = None
        self._http_runner = None

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
            except Exception:
                pass
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

    async def _do_write(self):
        await asyncio.sleep(0.5)
        try:
            tmp = self.state_path.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
            os.replace(tmp, self.state_path)
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
            except Exception:
                pass
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

    def audit(self, agent: str, action: str, detail: str = ""):
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

    async def broadcast_instances(self, payload: dict, exclude: Optional[str] = None):
        for iid, info in list(self.instances.items()):
            if iid == exclude:
                continue
            await self.send_to_instance(iid, payload)

    # ------------------- instances meta -------------------
    def instances_snapshot(self) -> list[dict]:
        out = []
        seen = set()
        for iid, info in self.instances.items():
            seen.add(iid)
            meta = self.state["instances_meta"].get(iid, {})
            out.append({
                "id": iid,
                "name": info.get("name", iid),
                "project": info.get("project", ""),
                "status": info.get("status", ""),
                "task": info.get("task", ""),
                "workload": info.get("workload", 0),
                "online": info.get("online", False),
                "role": meta.get("role", ""),
                "paused": meta.get("paused", False),
            })
        # include persisted-but-offline instances
        for iid, meta in self.state["instances_meta"].items():
            if iid in seen:
                continue
            out.append({
                "id": iid,
                "name": meta.get("name", iid),
                "project": meta.get("project", ""),
                "status": "",
                "task": "",
                "workload": 0,
                "online": False,
                "role": meta.get("role", ""),
                "paused": meta.get("paused", False),
            })
        return out

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
                    instance_id = msg.get("id")
                    if not instance_id:
                        continue
                    name = msg.get("name", instance_id)
                    project = msg.get("project", "")

                    async with self.lock:
                        existing = self.instances.get(instance_id)
                        if existing and existing.get("ws") is not ws:
                            try:
                                await existing["ws"].close()
                            except Exception:
                                pass

                        self.instances[instance_id] = {
                            "ws": ws,
                            "name": name,
                            "project": project,
                            "online": True,
                            "status": "online",
                            "task": "",
                            "workload": 0,
                        }
                        # persist meta
                        meta = self.state["instances_meta"].setdefault(instance_id, {})
                        meta.update({"name": name, "project": project})
                        meta.setdefault("role", "")
                        meta.setdefault("paused", False)
                        self.audit(instance_id, "register", f"name={name} project={project}")
                        self.schedule_write()

                    # send memory init
                    init_payload = {
                        "type": "memory_init",
                        "memory": self.state["memory"],
                        "ts": now_iso(),
                    }
                    try:
                        await ws.send(json.dumps(init_payload, default=str))
                    except Exception:
                        pass

                    # send tasks init (focus on this instance's tasks)
                    my_tasks = [t for t in self.state["tasks"]
                                if t.get("assignee") == instance_id
                                and t.get("status") not in ("Done", "Cancelled")]
                    try:
                        await ws.send(json.dumps({
                            "type": "tasks_init",
                            "tasks": my_tasks,
                            "ts": now_iso(),
                        }, default=str))
                    except Exception:
                        pass

                    # deliver backlog
                    queued = list(self.backlog.get(instance_id, []))
                    self.backlog[instance_id].clear()
                    if queued:
                        try:
                            await ws.send(json.dumps({"type": "backlog", "messages": queued}, default=str))
                        except Exception:
                            pass

                    await self.broadcast_ui({
                        "type": "instance_online",
                        "instance": self.instances_snapshot(),
                        "id": instance_id,
                    })
                    await self.state_update({"instances": self.instances_snapshot()})

                elif mtype == "message":
                    if not instance_id:
                        continue
                    to = msg.get("to", "you")
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    entry = {
                        "id": f"msg-{len(self.state['messages']) + 1}",
                        "from": instance_id,
                        "to": to,
                        "text": text,
                        "ts": now_iso(),
                    }
                    async with self.lock:
                        self.state["messages"].append(entry)
                        self.audit(instance_id, "message", f"to={to}")
                        self.schedule_write()
                    if to == "you" or to == "ui":
                        await self.broadcast_ui({"type": "message", "message": entry})
                    else:
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
                    except Exception:
                        pass
                    await self.broadcast_ui({"type": "approval_request", "approval": ap})

                elif mtype == "memory_write":
                    if not instance_id:
                        continue
                    async with self.lock:
                        entry = {
                            "id": self.next_id("M"),
                            "key": msg.get("key", ""),
                            "value": msg.get("value", ""),
                            "type": msg.get("mem_type", "contract"),
                            "by": instance_id,
                            "ts": now_iso(),
                        }
                        self.state["memory"].append(entry)
                        self.audit(instance_id, "memory_write", entry["key"])
                        self.schedule_write()
                    await self.broadcast_ui({"type": "memory_write", "memory": entry})
                    await self.broadcast_instances({"type": "memory_write", "memory": entry}, exclude=instance_id)

                elif mtype == "broadcast":
                    if not instance_id:
                        continue
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    entry = {
                        "id": f"msg-{len(self.state['messages']) + 1}",
                        "from": instance_id,
                        "to": "all",
                        "text": text,
                        "ts": now_iso(),
                    }
                    async with self.lock:
                        self.state["messages"].append(entry)
                        self.audit(instance_id, "broadcast", text[:80])
                        self.schedule_write()
                    await self.broadcast_instances({"type": "message", **entry}, exclude=instance_id)
                    await self.broadcast_ui({"type": "message", "message": entry})

                elif mtype == "typing":
                    if not instance_id:
                        continue
                    await self.broadcast_ui({
                        "type": "typing",
                        "id": instance_id,
                        "value": bool(msg.get("value", False)),
                    })

                elif mtype == "task_create":
                    if not instance_id:
                        continue
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
                        }
                        if self.has_cycle(self.state["tasks"] + [task]):
                            self.state["counters"]["T"] -= 1
                            try:
                                await ws.send(json.dumps({
                                    "type": "error",
                                    "error": "cyclic task dependencies",
                                    "ref": title,
                                }))
                            except Exception:
                                pass
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
                    t = next((x for x in self.state["tasks"] if x["id"] == tid), None)
                    if not t or not status:
                        continue
                    t["status"] = status
                    self.audit(instance_id, "task_status", f"{tid}->{status}")
                    self.schedule_write()
                    await self.state_update({"tasks": self.state["tasks"]})

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
            if not text:
                await ws.send_json({"type": "error", "error": "empty message"})
                return
            entry = {
                "id": f"msg-{len(self.state['messages']) + 1}",
                "from": "you",
                "to": to,
                "text": text,
                "ts": now_iso(),
            }
            async with self.lock:
                self.state["messages"].append(entry)
                self.audit("you", "message", f"to={to}")
                self.schedule_write()
            if to == "all":
                await self.broadcast_instances({"type": "message", **entry})
            else:
                await self.send_to_instance(to, {"type": "message", **entry})
            await self.broadcast_ui({"type": "message", "message": entry})

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
            v.setdefault("ballots", {})["you"] = option
            self.audit("you", "vote", f"{vote_id}={option}")
            self.schedule_write()
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
            async with self.lock:
                fid = self.next_id("F")
                flow = {
                    "id": fid,
                    "name": data.get("name", ""),
                    "trigger": data.get("trigger", ""),
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
    async def http_index(self, request):
        if INDEX_PATH.exists():
            return web.FileResponse(INDEX_PATH)
        return web.Response(
            text="<h1>Agent Mesh</h1><p>UI placeholder. Put index.html in this directory.</p>",
            content_type="text/html",
        )

    async def http_status(self, request):
        return web.json_response({
            "instances": self.instances_snapshot(),
            "messages": self.state["messages"][-50:],
            "tasks": self.state["tasks"],
            "memory": self.state["memory"],
            "approvals": self.state["approvals"],
            "audit": self.state["audit"][-50:],
        })

    async def http_state(self, request):
        return web.json_response(self.state)

    async def http_send(self, request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        to = body.get("to", "all")
        text = (body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "empty text"}, status=400)
        entry = {
            "id": f"msg-{len(self.state['messages']) + 1}",
            "from": "you",
            "to": to,
            "text": text,
            "ts": now_iso(),
        }
        async with self.lock:
            self.state["messages"].append(entry)
            self.audit("you", "message", f"to={to} (REST)")
            self.schedule_write()
        if to == "all":
            await self.broadcast_instances({"type": "message", **entry})
        else:
            await self.send_to_instance(to, {"type": "message", **entry})
        await self.broadcast_ui({"type": "message", "message": entry})
        return web.json_response({"ok": True, "message": entry})

    async def http_clear(self, request):
        self.state["messages"] = []
        self.audit("you", "clear_messages", "REST")
        self.schedule_write()
        await self.state_update({"messages": []})
        return web.json_response({"ok": True})

    # ------------------- lifecycle -------------------
    async def start(self):
        self.load_state()

        # WebSocket server for instances
        self._ws_server = await websockets.serve(
            self.handle_instance, "0.0.0.0", self.instance_port
        )

        # aiohttp UI/REST server
        app = web.Application()
        app.router.add_get("/", self.http_index)
        app.router.add_get("/ui", self.handle_ui_ws)
        app.router.add_get("/api/status", self.http_status)
        app.router.add_get("/api/state", self.http_state)
        app.router.add_post("/api/send", self.http_send)
        app.router.add_post("/api/clear", self.http_clear)

        self._http_runner = web.AppRunner(app)
        await self._http_runner.setup()
        site = web.TCPSite(self._http_runner, "0.0.0.0", self.ui_port)
        await site.start()

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
        except Exception:
            pass
        try:
            if self._http_runner:
                await self._http_runner.cleanup()
        except Exception:
            pass
        # flush pending write
        if self._write_task and not self._write_task.done():
            try:
                await self._write_task
            except Exception:
                pass
        try:
            tmp = self.state_path.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
            os.replace(tmp, self.state_path)
        except Exception:
            pass


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

    rows = [
        "        AGENT MESH — BROKER RUNNING",
        None,
        f" UI:        http://{ip}:{ui_port}",
        f" REST:      http://localhost:{ui_port}/api/",
        f" Instances: ws://localhost:{instance_port}",
        None,
        f" Connect snippet:  python connect.py",
    ]

    print(top)
    for r in rows:
        if r is None:
            print(sep)
        else:
            print("║" + pad(r) + "║")
    print(bot)


async def amain():
    broker = Broker()
    await broker.start()
    print_banner(local_ip(), broker.ui_port, broker.instance_port)
    try:
        await asyncio.Event().wait()
    finally:
        await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
