# Operations

Day-to-day running of an Agent Mesh broker: log paths, health checks,
metrics, backups, and the common restart / clear / reset rituals.

## Process layout

The broker is a single Python process. When installed via the launchd
template, it runs as `com.voidlabs.agent-mesh` under the current user's
`LaunchAgents`. Otherwise it's whatever shell you launched it from.

```
broker.py  (1 process)
  ├── asyncio loop (single)
  ├── websockets server on :8766  (instances)
  └── aiohttp server on  :8765  (UI + REST)
```

Both ports bind `0.0.0.0`.

## Log paths

The plist sets `MESH_LOG_FILE=~/Library/Logs/agent-mesh/broker.log`, which
activates the broker's built-in in-process rotation (10MB × 5 files). The
launchd `StandardOutPath` / `StandardErrorPath` are pointed at `/dev/null`
because the rotating file owns the real log.

| File                                       | Contents                          |
|--------------------------------------------|-----------------------------------|
| `~/Library/Logs/agent-mesh/broker.log`     | broker log (rotated 10MB × 5)     |

Tail it live:

```bash
tail -F ~/Library/Logs/agent-mesh/broker.log
```

Or, if you installed the Makefile, `make tail-logs` does the same.

When run interactively (`python3 broker.py`) without `MESH_LOG_FILE`, logs go
to your terminal. Use `python3 -u broker.py` for unbuffered output if you're
piping to a file.

## State + backups

| File                              | Purpose                                |
|-----------------------------------|----------------------------------------|
| `state.json`                      | Current persisted state                |
| `state.json.tmp`                  | Atomic write staging file              |
| `state.json.bak`                  | Backup written when load fails         |
| `~/.agent-mesh/backups/state.json.YYYY-MM-DD.bak` | Daily backup, last 7 kept |

To take a manual snapshot before doing something risky (from the clone dir,
`~/code/Claude-communication`):

```bash
cp state.json state.json.$(date +%F).manual
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
curl -X POST http://localhost:8765/api/clear -H "X-Mesh-Token: $MESH_TOKEN"
```

This removes the chat history but keeps channels and the audit log.

### Reset everything (nuclear)

Stop the broker, then (from the clone dir, `~/code/Claude-communication`):

```bash
mv state.json state.json.$(date +%F).snapshot
python3 broker.py
```

The broker comes back up with an empty state. Instances will re-register as
they reconnect.

### Drain backlog for one instance

There's no direct API for this — the simplest path is to spin up a throwaway
client with the matching `INSTANCE_ID`, let it drain the backlog (printed to
stdout), then disconnect.

## Capacity notes

- The audit log is capped at 1000 entries in `state.json`; daily backups under
  `~/.agent-mesh/backups/` preserve the full history.
- Per-instance backlog is byte-budgeted (256KB) — once a slow instance's queue
  exceeds the budget, the oldest queued messages are dropped.
- `state.json` typically stays well under 1 MB even after weeks of use.
