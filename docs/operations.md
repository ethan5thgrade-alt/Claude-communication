# Operations

Day-to-day running of an Agent Mesh broker: log paths, health checks,
metrics, backups, and the common restart / clear / reset rituals.

## Process layout

The broker is a single Python process. When installed via the launchd
template (batch 7), it runs as `com.voidlabs.agent-mesh` under the current
user's `LaunchAgents`. Otherwise it's whatever shell you launched it from.

```
broker.py  (1 process)
  ├── asyncio loop (single)
  ├── websockets server on :8766  (instances)
  └── aiohttp server on  :8765  (UI + REST)
```

Both ports bind `0.0.0.0`.

## Log paths

When run from the launchd plist:

| File                                         | Contents                          |
|----------------------------------------------|-----------------------------------|
| `~/Library/Logs/agent-mesh/out.log`          | stdout — banner + INFO logs       |
| `~/Library/Logs/agent-mesh/err.log`          | stderr — tracebacks, ERROR logs   |

Tail them live:

```bash
tail -F ~/Library/Logs/agent-mesh/out.log ~/Library/Logs/agent-mesh/err.log
```

Or, if you installed the Makefile, `make tail-logs` does the same.

When run interactively (`python3 broker.py`), logs go to your terminal. Use
`python3 -u broker.py` for unbuffered output if you're piping to a file.

## State + backups

| File                              | Purpose                                |
|-----------------------------------|----------------------------------------|
| `state.json`                      | Current persisted state                |
| `state.json.tmp`                  | Atomic write staging file              |
| `state.json.bak`                  | Backup written when load fails         |
| `state.json.v<n>.bak`             | Pre-migration backup (batch 5)         |
| `state.json.YYYY-MM-DD.bak`       | Daily backup, last 7 kept (batch 5)    |

To take a manual snapshot before doing something risky:

```bash
cp ~/agent-mesh/state.json ~/agent-mesh/state.json.$(date +%F).manual
```

## Health endpoint

`GET /api/health` returns 200 with a small JSON body:

```json
{
  "ok": true,
  "uptime_s": 12345,
  "build": "abc1234",
  "instances_online": 2
}
```

Quick poll:

```bash
curl -s http://localhost:8765/api/health | jq
```

A 200 here means the asyncio loop is alive and serving HTTP. If the response
hangs or returns 5xx, the loop is wedged — see the troubleshooting page.

## Metrics endpoint

`GET /api/metrics` returns Prometheus text format. Wire it into your
existing scraper if you have one:

```
# HELP agent_mesh_messages_total Total messages relayed
# TYPE agent_mesh_messages_total counter
agent_mesh_messages_total 4711

# HELP agent_mesh_ws_connections Current WebSocket connections
# TYPE agent_mesh_ws_connections gauge
agent_mesh_ws_connections{kind="instance"} 2
agent_mesh_ws_connections{kind="ui"} 1

# HELP agent_mesh_backlog_size Pending messages queued per instance
# TYPE agent_mesh_backlog_size gauge
agent_mesh_backlog_size{instance="cc2"} 3
```

A useful one-liner for a quick look:

```bash
curl -s http://localhost:8765/api/metrics | grep -v '^#'
```

## Common ops tasks

### Restart

If you installed via launchd:

```bash
make restart           # uses launchctl kickstart -k
```

Otherwise, Ctrl-C the process and run `python3 broker.py` again. The state
is restored from disk so no in-flight tasks are lost — though anything in
per-instance backlogs that hadn't been written yet is dropped.

### Clear messages

```bash
curl -X POST http://localhost:8765/api/clear
# or
python3 cli.py clear
```

This removes the chat history but keeps tasks, memory, audit, and approvals.

### Reset everything (nuclear)

Stop the broker, then:

```bash
mv ~/agent-mesh/state.json ~/agent-mesh/state.json.$(date +%F).snapshot
python3 broker.py
```

The broker comes back up with an empty state. Instances will re-register as
they reconnect.

### Quiesce all instances

Use the UI's "Emergency Stop" button (or `POST /api/emergency_stop`). The
broker sends `STOP — await instructions` to every connected instance and
records an audit entry. Resume with the matching "Resume All" button.

### Drain backlog for one instance

There's no direct API for this — the simplest path is to spin up a throwaway
client with the matching `INSTANCE_ID`, let it drain the backlog (printed to
stdout), then disconnect.

## Capacity notes

- The audit log self-trims at 5000 entries (`broker.py:120`).
- Per-instance backlog is a `deque(maxlen=100)` (`broker.py:62`) — older
  messages are silently dropped.
- The UI bootstrap payload sends the last 200 messages and last 200 audit
  entries; older entries are only visible via `/api/state`.
- `state.json` typically stays under 1 MB even after weeks of use. If it
  grows past 10 MB you probably have something writing huge values into
  `broker_memory(...)`.
