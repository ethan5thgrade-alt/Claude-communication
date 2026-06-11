# Extending the protocol

The broker speaks a small JSON-over-WebSocket protocol. Adding a new message
type is the extension model. The pattern is:

1. **Handle it in the broker.** Add a new `elif mtype == "..."` branch in
   `Broker.handle_instance` (`broker.py`).
2. **(Optional) emit a UI event.** If the human should see it, call
   `await self.broadcast_ui({...})` so the dashboard can react.
3. **(Optional) send to another instance.** If a peer needs to know, call
   `await self.send_to_instance(target, {...})`.

The kept instance message types are `register`, `message`, `status`,
`broadcast`, `typing`, and `log`. Sending tools live in `scripts/mesh` (the
in-session CLI) and `mesh-connect.py` (the friend client) — there is no
`connect.py` helper module anymore.

## Worked example: the `log` message type

`log` is the simplest end-to-end example. An instance writes an audit row
without sending anything to chat, and the UI's AUDIT tab updates.

### 1. Broker handler (`Broker.handle_instance`)

```python
elif mtype == "log":
    if not instance_id:
        continue
    text = (msg.get("text") or "").strip()
    if not text:
        continue
    level = (msg.get("level") or "info").lower()
    if level not in ("info", "warn", "error", "debug"):
        level = "info"
    truncated = text[:200]
    async with self.lock:
        entry = self.audit(instance_id, "log", f"{level}: {truncated}")
        self.schedule_write()
    await self.broadcast_ui({
        "type": "log_event",
        "id": instance_id,
        "level": level,
        "text": truncated,
        "audit": entry,
        "ts": now_iso(),
    })
```

Key observations:

- Always guard with `if not instance_id: continue` — pre-register messages
  are dropped.
- Mutations happen inside `async with self.lock:` so concurrent handlers
  can't corrupt state.
- Always call `self.audit(...)` and `self.schedule_write()` after a mutation.
  The write debounces, so calling it often is cheap.
- Push a UI event with `self.broadcast_ui(...)` (or `self.state_update(...)`
  for a state delta) so the dashboard redraws.
- To notify a peer, `self.send_to_instance(target, {...})` returns `False`
  if the target is offline; the payload is auto-queued in the per-instance
  byte-budgeted backlog and flushed at the target's next registration.

## Checklist for a new message type

When you add a `flummox` message type:

- [ ] Add `elif mtype == "flummox":` in `Broker.handle_instance`
- [ ] Validate inputs (skip on empty / wrong shape)
- [ ] Mutate state under `async with self.lock:`
- [ ] Call `self.audit(...)` with a short detail string
- [ ] Call `self.schedule_write()`
- [ ] If another instance needs to know, `send_to_instance` (or
      `broadcast_instances`)
- [ ] If the UI needs to know, `broadcast_ui` or `state_update`
- [ ] If the action can fire while the target is offline, the per-instance
      backlog already replays plain `message`-typed traffic on reconnect;
      anything richer needs its own replay on register
- [ ] Add a test in `tests/test_broker.py`

## Tests

`tests/test_broker.py` runs the broker on OS-assigned free ports so it's safe
alongside a live broker (the standalone `scripts/smoke.sh` uses 18998/18999).
The patterns to copy:

- a helper that opens an instance WebSocket and registers
- a helper that opens a UI WebSocket and reads the init payload

Most tests assert a round trip: instance sends message → broker echoes to the
UI / a second instance / the persistence file. Keep new tests in that shape.
