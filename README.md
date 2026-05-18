# Agent Mesh

**Local multi-agent coordination for Claude Code.** Run a tiny broker on
your laptop, point your Claude Code instances at it, and message them from
your phone (or from each other) — tasks, shared memory, approvals,
audit trail, all on the LAN. No cloud, no accounts.

## Quickstart

```bash
# 1. install deps
python3 -m pip install --user websockets aiohttp

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
```

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

## Non-Python clients

A zero-dependency TypeScript client lives in [`clients/`](./clients/). It
mirrors `connect.py` and runs on Node 22+, Bun, Deno, and in browsers. See
[`clients/README.md`](./clients/README.md).

## Security — shared-token auth

By default the broker binds to `0.0.0.0` and accepts any LAN connection. For
shared networks, set a shared token and every endpoint will require it.

```bash
export MESH_TOKEN=$(openssl rand -hex 16)
python3 broker.py       # logs "Shared-token auth ENABLED"
# in another terminal:
export MESH_TOKEN=...    # same value
python3 connect.py
```

`cli.py` sends `X-Mesh-Token: $MESH_TOKEN` automatically; for raw curl:

```bash
curl -X POST http://localhost:8765/api/send \
     -H "X-Mesh-Token: $MESH_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"to":"cc1","text":"hi"}'
```

The UI WS expects `?token=...` in the query string. See
[docs/security.md](docs/security.md) for the full model. Unset or empty
`MESH_TOKEN` disables auth.

## File map

```
agent-mesh/
├── broker.py                      # Core relay: WS on 8766 + HTTP/UI on 8765
├── connect.py                     # Python instance snippet
├── cli.py                         # REST sender for terminal use
├── index.html                     # Single-file UI
├── state.json                     # Persisted state (created on first run)
├── Makefile                       # dev / test / install-service / tail-logs / …
├── com.voidlabs.agent-mesh.plist  # launchd template (auto-start on Mac boot)
├── tests/test_broker.py           # broker test suite
├── clients/                       # Non-Python clients (TypeScript)
├── docs/                          # Detailed documentation (see table above)
├── README.md
└── ROADMAP.md                     # 100-item build-out plan
```

## Tests

```bash
python3.13 -m pytest tests/ -v
# or
make test
```

Tests spin the broker up on alternate ports, so they're safe to run alongside
a live broker.
