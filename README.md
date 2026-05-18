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

## File map

```
agent-mesh/
├── broker.py          # Core relay: WS on 8766 + HTTP/UI on 8765
├── connect.py         # Snippet each Claude Code instance runs
├── cli.py             # REST sender for terminal use
├── index.html         # Full UI — single self-contained file
├── state.json         # Persisted state (created on first run)
├── tests/
│   └── test_broker.py
├── docs/              # Detailed documentation (see table above)
├── README.md
└── ROADMAP.md         # 100-item build-out plan
```

## Tests

```bash
python3 -m pytest tests/ -v
```

Tests spin the broker up on alternate ports (18765/18766), so they're safe
to run alongside a live broker.
