# Architecture

Agent Mesh is a small relay server that lets multiple Claude Code instances and
a human (via the web UI) talk to each other on a local network. There are three
roles in the system:

- **Broker** (`broker.py`) — single process running on the host machine. Owns
  the persisted state and relays messages between everyone else.
- **Instance** — a Claude Code session that registers itself over a WebSocket
  and can send/receive messages, status updates, and audit log entries.
  Sessions are wired in via `scripts/mesh-claude`; a friend on another machine
  joins with `mesh-connect.py`.
- **UI** (`index.html`) — a browser client that connects to the broker over a
  separate WebSocket. Used by the human operator from a phone or laptop.

```
┌─────────────┐   ws://host:8766   ┌─────────────┐   ws://host:8765/ui   ┌─────────────┐
│  Instance   │ ──────────────────▶│             │◀──────────────────────│     UI      │
│  (cc1)      │                    │   Broker    │                       │ (browser)   │
└─────────────┘                    │  (state.json,│                       └─────────────┘
                                   │   audit log)│
┌─────────────┐   ws://host:8766   │             │   http://host:8765/api/ ┌──────────┐
│  Instance   │ ──────────────────▶│             │◀────────────────────────│   CLI    │
│  (cc2)      │                    └─────────────┘                         │ (curl)   │
└─────────────┘                                                            └──────────┘
```

The broker listens on two ports:

| Port | Protocol | Purpose                                |
|-----:|----------|----------------------------------------|
| 8765 | HTTP     | Serves `index.html`, REST API, UI WS   |
| 8766 | WS       | Instance-to-broker WebSocket           |

Both ports bind `0.0.0.0` so any device on the same LAN can reach them.

## State

The broker's source of truth lives in memory in `Broker.state` and is flushed
to `state.json` after every mutation (debounced by ~0.5s via
`schedule_write`). On startup the broker loads `state.json` and falls back to
an empty state with a `.bak` copy if the file is corrupt.

The state schema (see the empty-state initializer in `broker.py`):

```python
{
  "messages":  [...],   # all relayed messages
  "audit":     [...],   # append-only audit log (capped at 1000 in-state)
  "channels":  [...],   # named server-side member groups
  "instances_meta": {}, # persisted per-instance role/name/project
  "counters":  {...},   # monotonic id counters
}
```

The audit log is trimmed to 1000 entries in `state.json`; daily backups under
`~/.agent-mesh/backups/` keep the full history. Instances that are currently
disconnected still appear in `instances_meta` so the sidebar can show their
last known role. Messages destined for an offline instance go into a
per-instance byte-budgeted backlog (256KB) and are flushed on reconnect.

## Sequence diagrams

### Instance registration

```mermaid
sequenceDiagram
    autonumber
    participant CC as Instance (cc1)
    participant B as Broker
    participant UI as UI client(s)

    CC->>B: WS connect ws://host:8766
    CC->>B: {type: "register", id, name, project}
    B->>B: update instances + instances_meta, audit "register"
    alt backlog non-empty
        B-->>CC: {type: "backlog", messages: [...]}
    end
    B-->>UI: {type: "instance_online", instance: snapshot}
    B-->>UI: {type: "state_update", delta: {instances}}
```

The optional `backlog` payload makes registration resumable: a re-launched
agent receives any messages that arrived while it was offline without needing
to query.

### Message relay (instance to instance)

```mermaid
sequenceDiagram
    autonumber
    participant CC1 as Instance cc1
    participant B as Broker
    participant CC2 as Instance cc2
    participant UI as UI

    CC1->>B: {type: "message", to: "cc2", text: "..."}
    B->>B: append to state.messages, audit
    alt cc2 online
        B-->>CC2: {type: "message", from: "cc1", to: "cc2", text}
    else cc2 offline
        B->>B: backlog["cc2"].append(payload)
    end
    B-->>UI: {type: "message", message: entry}
```

The UI always gets a copy so the human sees the relayed traffic in the chat
thread (rendered as `[RELAY] cc1→cc2`).

### Channel fan-out (server-side groups)

A channel is a named server-side list of members. Sending to
`to: "channel:<id>"` fans out one message per member, each tagged with
`channel=<id>`. Bots that reply preserve the tag, so the UI filter is a
single equality check (`m.channel === channelId`) and historical 1-on-1
messages never leak into the channel thread.

```mermaid
sequenceDiagram
    autonumber
    participant U as User (UI)
    participant B as Broker
    participant CC as Channel ch_xxx
    participant A as cc-alpha
    participant V as cc-bravo

    U->>B: POST /api/send {to: "channel:ch_xxx", text: "hey team"}
    B->>CC: lookup members [cc-alpha, cc-bravo]
    B->>A: msg {to: cc-alpha, channel: ch_xxx, text: "hey team"}
    B->>V: msg {to: cc-bravo, channel: ch_xxx, text: "hey team"}
    A->>B: reply {from: cc-alpha, to: you, channel: ch_xxx, text: "on it"}
    V->>B: reply {from: cc-bravo, to: you, channel: ch_xxx, text: "same"}
    B-->>U: push all msgs with channel=ch_xxx
    Note over U: filter: m.channel === "ch_xxx" → shown in channel thread
```

Bot replies inherit the original channel via the bot's `orig_channel`
extraction; agent-to-agent direct messages (no channel) are intentionally
muted to prevent loops, so channels are the canonical path for multi-agent
coordination.

## Concurrency model

The broker runs one asyncio event loop and one `asyncio.Lock` guarding state
mutations. WebSocket handlers are coroutines (`handle_instance`,
`handle_ui_ws`) and REST handlers are aiohttp coroutines. All persistence
writes are scheduled — never inline — so a burst of messages collapses into a
single `state.json` write.

Instance connections use the `websockets` library with `ping_interval=20`
and `ping_timeout=20`. UI connections use aiohttp's built-in WebSocket
server. There is no cross-broker federation — every mesh is a single host.

## File map

| File                | Role                                               |
|---------------------|----------------------------------------------------|
| `broker.py`         | All server-side logic: WS handlers, REST, state, audit |
| `scripts/mesh`      | In-session CLI (send / inbox / who / hook)         |
| `scripts/mesh-claude` | Launch a Claude Code session wired into the mesh |
| `mesh-connect.py`   | Zero-dep friend client for another machine         |
| `index.html`        | Single-file UI (chat, channels, audit)             |
| `state.json`        | Persisted state, created on first write            |
| `tests/`            | pytest suite, runs broker on OS-assigned free ports |
