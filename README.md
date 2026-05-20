# Agent Mesh

**Local multi-agent coordination for Claude Code.** Run a tiny broker on
your laptop, point your Claude Code instances at it, and message them from
your phone (or from each other) — tasks, shared memory, approvals,
audit trail, all on the LAN. No cloud, no accounts.

📖 **[Read the docs site →](https://ethan5thgrade-alt.github.io/Claude-communication/)** ·
**[Get started in 5 minutes →](https://ethan5thgrade-alt.github.io/Claude-communication/getting-started.html)** ·
**[Examples →](https://ethan5thgrade-alt.github.io/Claude-communication/examples.html)**

## Quickstart

```bash
# 1. install deps (zeroconf optional, enables mDNS LAN discovery)
python3 -m pip install --user websockets aiohttp
python3 -m pip install --user zeroconf   # optional

# 2. run the broker
python3 broker.py

# 3. connect an instance (from inside a Claude Code session)
python3 connect.py
```

Open `http://localhost:8765` (or `http://<lan-ip>:8765` from your phone)
for the UI.

For the narrative walk-through with two instances talking to each other,
see [docs/quickstart.md](docs/quickstart.md).

## Documentation

| Page                                         | What's in it                                        |
|----------------------------------------------|-----------------------------------------------------|
| [Quickstart](docs/quickstart.md)             | Full tutorial: install → 2 instances → first task   |
| [Architecture](docs/architecture.md)         | Broker / instance / UI roles + mermaid diagrams     |
| [Security](docs/security.md)                 | LAN exposure model, shared-token auth, TLS guidance |
| [Operations](docs/operations.md)             | Log paths, health & metrics, backups, restart       |
| [Extending](docs/extending.md)               | How to add a new message type, worked example       |
| [Troubleshooting](docs/troubleshooting.md)   | Firewall, mDNS, reconnect storms, blank UI, etc.    |

## Helper reference

From inside a Claude Code REPL after `import connect`:

```python
broker_send("Task complete.")                      # → human
broker_send("Match my format.", to="cc2")          # → another instance
broker_broadcast("API contract finalized.")
broker_status("Writing SSE endpoint", workload=80)
ok = broker_approve_and_wait("Drop prod table", risk="high", timeout=300)
broker_memory("SSE_FORMAT", "{pct, ticker}", mem_type="contract")
broker_task_create("Write CSV parser", assignee="cc2", priority="high")
broker_task_done("T003", result="merged in PR #41")
broker_vote_and_wait("Ship M5?", ["yes", "no"])
broker_log("retry after 503", level="warn")        # → audit row, no chat
```

For typed event handling, call `connect.parse_event(payload)` inside your
incoming-message hook — it returns a `MessageEvent` / `TaskAssignedEvent` /
`MemoryEvent` / etc. dataclass (with IDE field help) for known event types,
or `None` for unknown ones. The existing dict-based path is unaffected.

## Auto-start on Mac

```bash
make install-service     # copy plist → ~/Library/LaunchAgents, launchctl load
make status              # show whether it's running
make tail-logs           # follow stdout + stderr
make restart-service     # unload + load
make uninstall-service   # stop and remove
```

Logs land in `~/Library/Logs/agent-mesh/{out,err}.log`. See
[docs/operations.md](docs/operations.md) for log rotation and the plist
template details.

## Plugin bridge

If you have Claude Code plugins installed under
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, the broker scans
them at startup and exposes them through a discovery-only bridge — it returns
the resolved skill/agent/command path + manifest, never executes plugin code.

```bash
curl http://localhost:8765/api/plugins
curl http://localhost:8765/api/plugins/apple-hig-expert
```

From an instance: `broker_plugin_invoke("apple-hig-expert", "apple-hig-expert")`
fires a request; listen for `plugin_invoke_result` on the incoming stream.
The UI's PLUGINS tab groups everything by marketplace.

## Non-Python clients

A zero-dependency TypeScript client lives in [`clients/`](./clients/). It
mirrors `connect.py` and runs on Node 22+, Bun, Deno, and in browsers. See
[`clients/README.md`](./clients/README.md).

## REST API

| Method | Path             | Purpose                                          |
|--------|------------------|--------------------------------------------------|
| GET    | `/api/status`    | Snapshot (instances, last 50 msgs, tasks, etc.)  |
| GET    | `/api/state`     | Full persisted state                             |
| GET    | `/api/health`    | Liveness + uptime + online count + build sha     |
| GET    | `/api/metrics`   | Prometheus text-format metrics                   |
| GET    | `/api/instances` | List of connected/known instances                |
| GET    | `/api/tasks`     | All tasks                                        |
| GET    | `/api/memory`    | All shared memory entries                        |
| GET    | `/api/plugins`   | Catalog of installed Claude Code plugins         |
| POST   | `/api/send`      | Send a message `{to, text}`                      |
| POST   | `/api/clear`     | Clear message history                            |
| POST   | `/api/task`      | Create a task `{title, assignee, priority, deps}`|
| POST   | `/api/memory`    | Write memory `{key, value, mem_type}`            |

## Security — shared-token auth

By default the broker accepts any LAN connection. For shared networks, set
`MESH_TOKEN` and every endpoint will require it:

```bash
export MESH_TOKEN=$(openssl rand -hex 16)
python3 broker.py
# instances + cli.py read the env var automatically; raw curl needs the header:
curl -X POST http://localhost:8765/api/send \
     -H "X-Mesh-Token: $MESH_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"to":"cc1","text":"hi"}'
```

The UI WS expects `?token=...` in the query string. See
[docs/security.md](docs/security.md) for the full model. Unset or empty
`MESH_TOKEN` disables auth.

## LAN auto-discovery (mDNS)

If `zeroconf` is installed the broker advertises itself as
`_agent-mesh._tcp.local.`. `python3 cli.py discover` lists every broker on
the LAN; `connect.py` auto-falls-back to mDNS when `BROKER_URL` is unset and
localhost fails. To force a specific broker:

```bash
BROKER_URL=ws://192.168.1.42:8766 python3 connect.py
```

Some networks block multicast — set `BROKER_URL` manually in that case.

## CLI

`cli.py` wraps the REST surface:

```bash
python3 cli.py send cc1 "What are you working on?"
python3 cli.py status | state | clear | health | metrics
python3 cli.py instances | tasks | memory | discover
python3 cli.py task "write CSV parser" --assignee cc2 --priority high
python3 cli.py memorize API_SHAPE "{pct, ticker}"
```

## Tests, pre-commit, CI

```bash
python3.13 -m pytest tests/ -v   # broker tests + client helper tests
bash scripts/smoke.sh             # spins broker on 18998/18999, exercises REST
pre-commit install                # ruff + check-yaml + EOF hygiene
```

GitHub Actions runs the pytest matrix on Python 3.10/3.11/3.12/3.13 plus the
smoke script — see `.github/workflows/ci.yml`.

## File map

```
agent-mesh/
├── broker.py                      # Core relay: WS on 8766 + HTTP/UI on 8765
├── connect.py                     # Python instance snippet
├── cli.py                         # REST sender for terminal use
├── index.html                     # Single-file UI
├── state.json                     # Persisted state (created on first run)
├── Makefile                       # dev / test / install-service / tail-logs
├── com.voidlabs.agent-mesh.plist  # launchd template (auto-start on Mac boot)
├── tests/
│   ├── test_broker.py             # WS/REST protocol tests
│   └── test_clients.py            # End-to-end connect.py helper tests
├── clients/                       # Non-Python clients (TypeScript)
├── docs/                          # Detailed documentation (see table above)
├── scripts/smoke.sh               # REST smoke test
├── .github/workflows/ci.yml       # pytest matrix on push/PR
├── .pre-commit-config.yaml        # ruff + hygiene hooks
├── CONTRIBUTING.md                # branch/PR conventions
├── ROADMAP.md                     # 100-item build-out plan
└── README.md
```

Tests spin the broker up on alternate ports, so they're safe to run alongside
a live broker.
