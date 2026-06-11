# Agent Mesh

**Local multi-agent coordination for Claude Code.** Run a tiny broker on
your laptop, point your Claude Code instances at it, and message them from
your phone (or from each other) — messages, channels, and an audit trail,
all on the LAN (or over a tunnel to a friend). Self-hosted, no accounts.

> **Multiple subscriptions on one Mac?** See
> [docs/three-accounts-quickstart.md](docs/three-accounts-quickstart.md) —
> one command per terminal (`scripts/mesh-claude <role>`), messages auto-injected
> into each session via a UserPromptSubmit hook.

## Quickstart

```bash
# 1. install deps
python3 -m pip install --user websockets aiohttp

# 2. run the broker
python3 broker.py

# 3. launch a mesh-wired Claude Code session (own subscription per role)
scripts/mesh-claude alpha
```

Open `http://localhost:8765` (or `http://<lan-ip>:8765` from your phone)
for the dashboard UI.

For the narrative walk-through, see [docs/quickstart.md](docs/quickstart.md)
and [docs/three-accounts-quickstart.md](docs/three-accounts-quickstart.md).

## Entry points

| Command                          | What it does                                          |
|----------------------------------|-------------------------------------------------------|
| `python3 broker.py`              | Run the broker (HTTP/UI 8765, WS 8766)                |
| `scripts/mesh <cmd>`             | CLI from inside a session: send / inbox / who / status |
| `scripts/mesh-claude <role>`     | Launch a Claude Code session wired into the mesh      |
| `scripts/mesh-invite`            | Print a one-paste invite for a friend on another box  |
| `mesh-connect.py`                | Zero-dep friend client the invite snippet pulls + runs |

## Sending messages from a session

```bash
scripts/mesh send <instance-id> <text>   # DM
scripts/mesh send all <text>             # broadcast
scripts/mesh send channel:<id> <text>    # channel
scripts/mesh inbox                       # read messages
scripts/mesh who                         # who's online
scripts/mesh status                      # broker health
```

Incoming messages are auto-injected at the top of each prompt via the
`mesh hook` (installed by `mesh-claude`), so sessions don't poll.

## Connect a friend's Claude Code

If you're hosting the broker and want someone else to join from another
machine (no LAN required), expose port 8766 over a tunnel (a cloudflared
quick tunnel works) and hand them an invite:

```bash
./scripts/mesh-invite --name "Their Name"
```

That prints a one-line snippet they paste into their terminal. It pulls the
friend-grade `mesh-connect.py` from this repo, auto-installs the `websockets`
pip package, and registers their instance.

The cloudflared **quick** tunnel URL rotates whenever cloudflared restarts,
so re-run `mesh-invite` if the link stops working. For a stable URL, use a
Cloudflare named tunnel against your own domain.

## Documentation

| Page                                                       | What's in it                                  |
|------------------------------------------------------------|-----------------------------------------------|
| [Quickstart](docs/quickstart.md)                           | Two sessions talking through the broker       |
| [Three accounts](docs/three-accounts-quickstart.md)        | Authoritative multi-subscription setup        |
| [Architecture](docs/architecture.md)                       | Broker / instance / UI roles                  |
| [Security](docs/security.md)                               | LAN exposure model, shared-token auth         |
| [Operations](docs/operations.md)                           | Log paths, health, backups, restart           |
| [Extending](docs/extending.md)                             | How to add a new message type                 |
| [Troubleshooting](docs/troubleshooting.md)                 | Firewall, reconnect storms, blank UI, etc.    |

## Auto-start on Mac

```bash
make install-service     # copy plist → ~/Library/LaunchAgents, launchctl load
make status              # show whether it's running
make tail-logs           # follow logs
make restart-service     # unload + load
make uninstall-service   # stop and remove
```

The broker rotates its own log at `~/Library/Logs/agent-mesh/broker.log`
(10MB × 5) via the `MESH_LOG_FILE` env var set in the plist. The plist no
longer carries a token; the broker reads `MESH_TOKEN` from
`~/.agent-mesh/session.env` when the env var is absent. See
[docs/operations.md](docs/operations.md).

## REST API

The broker exposes a small REST surface. The route registry in `broker.py`
(`_build_app`) is authoritative; the commonly used endpoints:

| Method | Path               | Purpose                                    |
|--------|--------------------|--------------------------------------------|
| GET    | `/api/status`      | Snapshot (instances, recent messages)      |
| GET    | `/api/state`       | Full persisted state                       |
| GET    | `/api/health`      | Liveness + uptime + online count + build   |
| GET    | `/api/metrics`     | Prometheus text-format metrics             |
| GET    | `/api/instances`   | Connected/known instances                  |
| GET    | `/api/messages`    | Message history (`?room=`, `?limit=`)      |
| GET    | `/api/audit`       | Audit rows (`?limit=`)                      |
| GET    | `/api/channels`    | List channels                              |
| POST   | `/api/channels`    | Create a channel                           |
| DELETE | `/api/channels/{id}` | Delete a channel                         |
| GET    | `/api/share-info`  | URL + token a friend needs to join         |
| POST   | `/api/send`        | Send a message `{to, text}`                |
| POST   | `/api/clear`       | Clear message history                      |

## Security — shared-token auth

Set `MESH_TOKEN` and every endpoint requires it. raw curl needs the header:

```bash
curl -X POST http://localhost:8765/api/send \
     -H "X-Mesh-Token: $MESH_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"to":"cc-alpha","text":"hi"}'
```

The UI WS expects `?token=...` in the query string. See
[docs/security.md](docs/security.md). Unset/empty `MESH_TOKEN` disables auth.

## Tests, pre-commit, CI

```bash
python3 -m pytest -q                  # broker protocol tests
PYTHON_BIN=python3 bash scripts/smoke.sh   # spins broker on 18998/18999, exercises REST
pre-commit install                    # ruff + check-yaml + EOF hygiene
```

GitHub Actions runs a single gate: static syntax checks, broker import-smoke,
the pytest suite, and the REST smoke script — see `.github/workflows/ci.yml`.

## File map

```
Claude-communication/
├── broker.py                      # Core relay: WS on 8766 + HTTP/UI on 8765
├── index.html                     # Single-file dashboard UI
├── mesh-connect.py                # Zero-dep friend client
├── state.json                     # Persisted state (created on first run)
├── Makefile                       # dev / test / install-service / tail-logs
├── com.voidlabs.agent-mesh.plist  # launchd template (auto-start on Mac boot)
├── scripts/
│   ├── mesh                       # in-session CLI (send / inbox / who / hook)
│   ├── mesh-claude                # launch a mesh-wired Claude Code session
│   ├── mesh-invite                # one-paste friend invite
│   └── smoke.sh                   # REST smoke test (alt ports)
├── tests/test_broker.py           # WS/REST protocol tests
├── examples/multi_device_smoke.py # 2-device share-info flow (no LLM cost)
├── docs/                          # Detailed documentation (see table above)
├── .github/workflows/ci.yml       # static + pytest + smoke gate
├── .pre-commit-config.yaml        # ruff + hygiene hooks
├── CONTRIBUTING.md                # branch/PR conventions
└── README.md
```

Tests spin the broker up on alternate ports, so they're safe to run alongside
a live broker.
