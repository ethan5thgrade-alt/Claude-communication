# Security model

Agent Mesh is designed to run on a **trusted local network** between machines
you own. It is not hardened for hostile environments. This page lays out the
exact threat model so you can decide whether that's acceptable for your
setup.

## What the broker exposes

By default `broker.py` binds both ports on `0.0.0.0`:

| Port | Protocol | Listener           |
|-----:|----------|--------------------|
| 8765 | HTTP/WS  | UI + REST API      |
| 8766 | WS       | Instance WebSocket |

Any device that can route to your Mac on those ports can:

- Open the UI and read all messages, tasks, memory, audit, etc.
- POST to `/api/send` and inject messages
- Connect a fake instance via the instance WebSocket and impersonate any ID

This is fine on a home Wi-Fi network where you control every device. It is
**not** fine on coffee-shop Wi-Fi, conference Wi-Fi, or any network where
untrusted devices can reach you.

## Shared-token authentication (v1.1+)

If `MESH_TOKEN` is set in the broker's environment, every connection must
present the token:

- **Instances**: include `"token": "<value>"` in the `register` payload.
  `connect.py` reads `MESH_TOKEN` from its own env and forwards it.
- **UI**: connect to `ws://host:8765/ui?token=<value>`. Open the UI from
  `http://host:8765/?token=<value>` and the page propagates it.
- **REST**: include `X-Mesh-Token: <value>` on every request. The `cli.py`
  wrapper reads `MESH_TOKEN` from env automatically.

Without a matching token, connections are closed before the handshake
completes. Audit log records the rejected attempt.

Generate one with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

…and export it before starting the broker:

```bash
export MESH_TOKEN=<paste here>
python3 broker.py
```

The same value goes into the env on every machine that runs `connect.py`,
and the same value goes into any device that opens the UI.

(Implementation details and the exact rejection behaviour are owned by
batch 4; see that batch's tests for the canonical contract.)

## TLS

Agent Mesh **does not** terminate TLS in v1. Traffic between the broker and
every instance/UI is plain WebSocket and HTTP.

If you need encryption (for example, exposing the UI over Tailscale or to a
phone on cellular), terminate TLS at a reverse proxy and have the proxy
forward to `localhost:8765`. Tested setups:

- **Caddy**: `host.example.com { reverse_proxy localhost:8765 }`
- **nginx**: `proxy_pass http://127.0.0.1:8765;` with WebSocket upgrade
  headers on `/ui`
- **Tailscale Funnel**: `tailscale funnel 8765` exposes the UI over HTTPS
  with no config

When you do this, the instance WebSocket on 8766 should stay bound to
`127.0.0.1` or to your tailnet — there's no benefit to exposing it
publicly even with a token.

## Data at rest

`state.json` is plaintext JSON, written next to `broker.py`. It contains:

- Every message ever relayed (until you clear it)
- All shared memory entries — including anything an agent dumped there
- Audit log of every action

If you keep secrets out of `broker_memory(...)` calls and don't paste
credentials into chat, the file is uninteresting. If you do, that file is a
liability — back it up encrypted (`tar | gpg`) and don't sync it via Dropbox.

The launchd-managed install also writes:

- `~/Library/Logs/agent-mesh/out.log` — every banner + every audit line
- `~/Library/Logs/agent-mesh/err.log` — tracebacks

Both are world-readable by default. `chmod 600` if other users share the
machine.

## What's not covered

- **No authorization model.** Once an instance is connected, it can send to
  any ID, claim any task, write any memory entry. The token gates entry,
  not permissions inside the mesh.
- **No rate limiting** on instance messages (flow execution does have its
  own per-flow rate cap — see batch 2).
- **No replay protection** on the audit log. An attacker with file write
  access can rewrite history.
- **No sandboxing** of message contents. The UI escapes HTML, but if you
  pipe `state.json` into another tool, that tool needs to do its own
  escaping.

For anything beyond a personal/home setup, run the broker behind a real
reverse proxy with TLS, set `MESH_TOKEN` to a strong random value, and
firewall both ports off from the open internet.
