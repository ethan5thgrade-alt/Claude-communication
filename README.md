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

## Non-Python clients

A zero-dependency TypeScript client lives in [`clients/`](./clients/). It
mirrors the helper surface of `connect.py` and runs on Node 22+, Bun, Deno,
and in browsers.

```ts
import { connectMesh } from "./clients/connect.js";

const mesh = await connectMesh({ id: "ts1", name: "TS Bot", project: "OPTFINDER" });
mesh.on("message", (e) => console.log(`[${e.from}] ${e.text}`));
mesh.on("task_assigned", (e) => console.log("got task", e.task.id));
mesh.send("TypeScript client online.");
mesh.taskCreate("Write SSE parser", "cc2", "high");
```

Run the demo:

```bash
cd clients
bun run example.ts        # or: npx tsx example.ts
```

See [`clients/README.md`](./clients/README.md) for the full surface, the
auto-reconnect contract, and instructions for Node <22 (use the `ws`
polyfill).

## More than 4 instances

The UI handles up to 8 instances with an extended color palette. Just assign distinct `INSTANCE_ID` values (`cc5`, `cc6`, …) when you connect them. On mobile, the sidebar collapses into a horizontal scrollable strip of agent pills.

## Auto-start on Mac

The repo ships a launchd plist (`com.voidlabs.agent-mesh.plist`) and a `Makefile`
so the broker starts on every login and restarts itself if it ever crashes.

```bash
cd ~/agent-mesh

make install-service     # copy plist → ~/Library/LaunchAgents, launchctl load
make status              # show whether it's running
make tail-logs           # follow stdout + stderr
make restart-service     # unload + load (e.g. after editing broker.py)
make uninstall-service   # stop and remove
```

Logs land in `~/Library/Logs/agent-mesh/out.log` and `err.log`.
Other make targets: `make dev` (foreground), `make test`, `make help`.

### Editing the plist for a different setup

The shipped `com.voidlabs.agent-mesh.plist` hard-codes
`/usr/local/bin/python3.13` and `/Users/ethanstrauss/agent-mesh/` because
launchd does **not** expand `~` or `$HOME`. If your Python or repo lives
elsewhere, edit those three `<string>` entries (`ProgramArguments` and
`WorkingDirectory`) before `make install-service`. The two log paths under
`Library/Logs/agent-mesh/` should also be updated to your own home dir.

### Rotating the logs

If the logs grow large, drop a single line into
`/etc/newsyslog.d/agent-mesh.conf` (replace `ethanstrauss` with your username):

```
# logfilename                                       [owner:group]   mode count size when  flags
/Users/ethanstrauss/Library/Logs/agent-mesh/*.log   ethanstrauss:staff 644 5 5000 *     J
```

`newsyslog` runs hourly via launchd and will gzip-rotate the file once it
exceeds ~5 MB, keeping 5 archives.

## Tests

```bash
cd ~/agent-mesh
python3 -m pytest tests/ -v
# or:
make test
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
├── broker.py                      # Core relay: WS on 8766 + HTTP/UI on 8765
├── connect.py                     # Snippet each Claude Code instance runs
├── cli.py                         # REST sender for terminal use
├── index.html                     # Full UI — single self-contained file
├── state.json                     # Persisted state (created on first run)
├── Makefile                       # dev / test / install-service / tail-logs / …
├── com.voidlabs.agent-mesh.plist  # launchd template (auto-start on Mac boot)
├── tests/
│   └── test_broker.py             # tests covering relay/persistence/reconnect
├── clients/                       # Non-Python clients (TypeScript / JS)
│   ├── connect.ts                 # Same surface as connect.py
│   ├── example.ts
│   └── README.md
└── README.md
```
