# Agent Mesh

Local multi-agent coordination for Claude Code. Message any of your Claude Code instances from your phone or browser, let instances message each other through a shared broker, and manage tasks / automation flows / shared memory / approvals from one UI. Everything runs locally — no cloud, no accounts.

## Requirements

- Python 3.10+ (3.13 recommended)
- pip packages: `websockets`, `aiohttp` (tests also need `pytest`, `pytest-asyncio`)

```bash
python3 -m pip install --user websockets aiohttp pytest pytest-asyncio
```

## Setup

1. **Run the broker**
   ```bash
   cd ~/agent-mesh
   python3 broker.py
   ```
   The startup banner prints the LAN URL. Leave it running.

2. **Open the UI on your phone**
   Open `http://<your-mac-lan-ip>:8765` in mobile Safari/Chrome. The IP is shown in the banner. Both devices must be on the same Wi-Fi.

3. **Connect a Claude Code instance**
   In a Claude Code session, edit the three constants at the top of `connect.py`:
   ```python
   INSTANCE_ID = "cc1"        # unique per instance
   NAME        = "Claude 1"
   PROJECT     = "OPTFINDER"
   ```
   Then either run it directly for an interactive shell:
   ```bash
   python3 connect.py
   ```
   …or paste/import it into a Python REPL inside your Claude Code session and call the helpers:
   ```python
   broker_send("Task complete.")                      # → human
   broker_send("Match my format.", to="cc2")          # → another instance
   broker_broadcast("API contract finalized.")         # → all instances
   broker_status("Writing SSE endpoint", workload=80)  # → sidebar update
   broker_approve_request("Delete /scan", risk="medium", detail="Old clients 404")
   broker_memory("SSE_FORMAT", "{pct, ticker}", mem_type="contract")
   broker_task_create("Write CSV parser", assignee="cc2", priority="high")
   broker_task_claim("T003")
   broker_task_status("T003", "Review")
   broker_task_done("T003", result="merged in PR #41")
   ```

## Agent-to-agent task delegation

Any instance can hand a task to another instance. When a task is created with
`assignee="cc2"`, the broker pushes a `task_assigned` event to `cc2` (queueing
it in the backlog if cc2 is offline). When the assignee calls
`broker_task_done(...)`, the creator instance receives a `task_completed`
event with the result string.

On register, each instance also gets a `tasks_init` payload listing its open
assigned tasks, so a re-launched agent resumes with full context.

## Agent-to-agent messaging

Once two instances are connected (say `cc1` and `cc2`), either can message the other directly:

```python
# from inside cc1
broker_send("Use my event shape {pct, ticker}", to="cc2")
```

The UI shows these as `[RELAY] cc1→cc2` in the chat thread.

`broker_broadcast(text)` fans out to every other connected instance.

Shared memory written via `broker_memory(...)` is visible to all instances and shown in the MEMORY tab.

## REST API (curl / cli.py)

The broker exposes a small REST surface on `http://localhost:8765/api/`:

```bash
# Send from the terminal
curl -X POST http://localhost:8765/api/send \
     -H 'Content-Type: application/json' \
     -d '{"to":"cc1","text":"What are you working on?"}'

# Snapshot
curl http://localhost:8765/api/status

# Full persisted state
curl http://localhost:8765/api/state

# Clear message history
curl -X POST http://localhost:8765/api/clear
```

Or use the wrapper:

```bash
python3 cli.py send cc1 "What are you working on?"
python3 cli.py status
python3 cli.py state
python3 cli.py clear
```

## Security — shared-token auth

By default the broker binds to `0.0.0.0` and accepts any connection on the LAN. For shared networks (coworking, coffee shops, untrusted Wi-Fi), set a shared token and every endpoint will require it.

1. **Pick a token** (one-time):
   ```bash
   export MESH_TOKEN=$(openssl rand -hex 16)
   ```

2. **Start the broker with the same env set:**
   ```bash
   export MESH_TOKEN=...           # same value
   python3 broker.py
   ```
   The broker logs `Shared-token auth ENABLED` on startup.

3. **Connect instances** — `connect.py` reads `MESH_TOKEN` from the environment and includes it in the register payload:
   ```bash
   export MESH_TOKEN=...
   python3 connect.py
   ```
   A wrong/missing token gets `{"type": "auth_failed", "reason": "bad token"}` and the WS is closed.

4. **REST / `cli.py`** — `cli.py` sends `X-Mesh-Token: $MESH_TOKEN` automatically. From curl:
   ```bash
   curl -X POST http://localhost:8765/api/send \
        -H "X-Mesh-Token: $MESH_TOKEN" \
        -H 'Content-Type: application/json' \
        -d '{"to":"cc1","text":"hi"}'
   ```
   Missing/wrong header → `401`.

5. **UI WS** — pass `?token=...` in the query string when connecting to `/ui`. The bundled `index.html` running over the same origin can be wrapped to inject it; for now this gates remote-browser access.

If `MESH_TOKEN` is unset or empty, auth is disabled and the broker behaves exactly as before.

## More than 4 instances

The UI handles up to 8 instances with an extended color palette. Just assign distinct `INSTANCE_ID` values (`cc5`, `cc6`, …) when you connect them. On mobile, the sidebar collapses into a horizontal scrollable strip of agent pills.

## Tests

```bash
cd ~/agent-mesh
python3 -m pytest tests/ -v
```

Tests spin the broker up on alternate ports (18765/18766), so they're safe to run alongside a live broker.

## Troubleshooting

- **Phone can't reach the broker.** macOS firewall is blocking inbound on 8765. Either allow Python in System Settings → Network → Firewall, or run `sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add $(which python3)`.
- **`Address already in use`.** Another broker is running. Find it with `lsof -iTCP:8765 -sTCP:LISTEN` and kill it, or change ports inside `broker.py`.
- **Banner doesn't appear.** Use `python3 -u broker.py` — stdout buffering can hide the print until the first message.
- **Instance won't reconnect.** `connect.py` auto-reconnects with exponential backoff capped at 30s. If a reconnect storm starts, kill and re-run it.
- **`state.json` looks corrupted.** Delete or rename it — the broker will start with an empty state on next launch. (It also auto-backs-up to `state.json.bak` on read failure.)
- **WebSocket connect fails from a remote browser.** The UI uses `ws://<location.host>/ui`, so the WS port is implicit — just make sure 8765 is reachable, not 8766. Agent-to-agent traffic stays on localhost.

## File map

```
agent-mesh/
├── broker.py          # Core relay: WS on 8766 + HTTP/UI on 8765
├── connect.py         # Snippet each Claude Code instance runs
├── cli.py             # REST sender for terminal use
├── index.html         # Full UI — single self-contained file
├── state.json         # Persisted state (created on first run)
├── tests/
│   └── test_broker.py # 9 tests covering relay/persistence/reconnect
└── README.md
```
