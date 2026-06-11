# Troubleshooting

Symptoms and fixes for things that go wrong. Start at the top — issues are
roughly ordered by frequency.

## Phone or laptop can't reach the broker

**Symptom:** browser shows "can't connect" or hangs when you point it at
`http://<lan-ip>:8765`. `localhost:8765` works from the broker host.

**Cause:** the macOS application firewall is blocking inbound on 8765/8766.

**Fix:**

System Settings → Network → Firewall → toggle off, or click "Options…" and
add `python3` to the allow list. CLI alternative:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
     --add $(which python3)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
     --unblockapp $(which python3)
```

Verify with `nc -vz <lan-ip> 8765` from another machine on the LAN — it
should print `succeeded`.

## `Address already in use`

**Symptom:** `OSError: [Errno 48] Address already in use` on broker
startup.

**Cause:** another broker (or any process) is bound to 8765 or 8766.

**Fix:** find the offender and kill it.

```bash
lsof -iTCP:8765 -sTCP:LISTEN
lsof -iTCP:8766 -sTCP:LISTEN
kill <pid>
```

If you can't kill it (you don't own it), change the `UI_PORT` / `INSTANCE_PORT`
constants near the top of `broker.py`, and point clients at the new instance
port with `BROKER_URL=ws://localhost:<new>`.

## Banner doesn't appear

**Symptom:** you run `python3 broker.py` and the terminal sits silent. No
banner, no logs. But the broker actually works.

**Cause:** stdout buffering. The banner is `print()`-ed and Python is
holding it until enough output accumulates.

**Fix:**

```bash
python3 -u broker.py
```

Or just send something through the broker — the banner flushes as soon as
the next line of logging arrives.

## Instance won't reconnect

**Symptom:** terminal shows `[DISCONNECTED] ...; retry in N.Ns` over and
over, increasing delays.

**Diagnosis:** the friend client (`mesh-connect.py`) uses exponential backoff.
Persistent failures mean either:

- The broker isn't running — check `lsof -iTCP:8766 -sTCP:LISTEN`.
- The host/port is wrong — verify `BROKER_URL` matches the broker's IP.
- The OS-level firewall is blocking it (see the first section).
- You're behind a NAT that drops idle WebSocket pings.

**Fix:** kill the client (Ctrl-C) and re-run it after fixing the
underlying cause. Reconnection state isn't lost — any messages destined
for that instance are queued in the broker's per-instance backlog and
replayed on register.

## Reconnect storm

**Symptom:** broker logs show `register` from the same `INSTANCE_ID`
repeatedly, each reconnect closing the previous WebSocket. UI sidebar
flickers.

**Cause:** two clients running with the same `INSTANCE_ID`. Each kicks
the other off.

**Fix:** kill all but one, or relaunch one with a different `INSTANCE_ID`
(e.g. `scripts/mesh-claude <other-role>`) so they coexist.

## `state.json` looks corrupted

**Symptom:** broker startup warns `Corrupt state.json (...); backing up
and starting fresh`. You're now staring at an empty UI.

**Cause:** typically a partial write from a crash, or you edited the file
by hand and forgot a comma.

**Fix:** the broker already copied the bad file to `state.json.bak` (and
keeps dated daily backups under `~/.agent-mesh/backups/`). Inspect with:

```bash
python3 -m json.tool state.json.bak
```

`json.tool` will point at the line/column of the syntax error. Fix it,
then either copy back to `state.json` or merge by hand.

If you don't care about the history (from the clone dir):

```bash
rm state.json*
python3 broker.py
```

## Blank UI

**Symptom:** browser loads but the page is empty (or shows only the
header). DevTools console may show a WS error.

**Likely causes, in order:**

1. **WebSocket couldn't connect.** The UI uses `ws://<location.host>/ui`
   (i.e. port 8765, the same as the page). If the browser tab opened via
   HTTPS but the broker only speaks HTTP, the mixed-content rule
   blocks the WS. Either drop back to HTTP, or front the broker with a
   TLS-terminating proxy (see `security.md`).
2. **`index.html` not found.** The broker falls back to a placeholder if
   `INDEX_PATH.exists()` is False. Make sure `index.html` is in the same
   directory as `broker.py`.
3. **`MESH_TOKEN` mismatch.** If token auth is on, the UI WS handshake is
   rejected. The browser console will show a 401 / close on
   `/ui?token=...`. Re-open the page with the right `?token=` query
   param.

## Friend on another machine can't reach the broker

**Symptom:** a friend pastes the invite snippet but `mesh-connect.py` can't
connect.

**Causes & fixes:**

- The quick-tunnel URL rotated — re-run `scripts/mesh-invite` and resend.
- The broker host's port 8766 isn't exposed — make sure the cloudflared
  tunnel is up (`make status` shows the broker; check the tunnel separately).
- Wrong or missing `MESH_TOKEN` — the invite embeds the current token; a
  stale snippet 401s after a token rotation.

## WebSocket fails from a remote browser

**Symptom:** UI loads, but the sidebar never populates and DevTools shows
"WebSocket connection to … failed".

**Cause:** the UI uses `ws://<location.host>/ui` (port 8765) — there is no
separate port for UI WebSockets. The instance port (8766) doesn't need to
be reachable from the browser, only from instance clients.

**Fix:** make sure 8765 is open on the broker host. Don't bother opening
8766 to remote browsers; agent-to-agent traffic typically stays on the
host or LAN.

## Tests failing locally

**Symptom:** `python3 -m pytest` returns red on a clean clone.

**Common fixes:**

- Make sure dev deps are installed: `pip install -r requirements-dev.txt`.
- The suite binds OS-assigned free ports (port 0), so it won't collide with a
  live broker. The standalone `scripts/smoke.sh` uses 18998/18999 —
  `lsof -iTCP:18998 -sTCP:LISTEN` if that script hangs.
- Run with `-v` so you can see which test is hanging.

## Still stuck?

- `curl http://localhost:8765/api/state | python3 -m json.tool` dumps the
  full broker state — a good first thing to look at when behaviour is
  unexplained.
- `~/Library/Logs/agent-mesh/broker.log` has the rotating broker log
  (tracebacks included) when running under launchd.
- Cross-reference what you're seeing with `docs/architecture.md` — the
  sequence diagrams there show the exact event order.
