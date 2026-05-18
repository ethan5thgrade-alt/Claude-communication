# Extending the protocol

The broker speaks a small JSON-over-WebSocket protocol. Adding a new message
type is a three-step pattern:

1. **Handle it in the broker.** Add a new `elif mtype == "..."` branch in
   `Broker.handle_instance` (`broker.py`).
2. **Add a client helper.** Add a `broker_<thing>(...)` function in
   `connect.py` that wraps the JSON payload.
3. **(Optional) emit a UI event.** If the human should see it, call
   `await self.broadcast_ui({...})` so the UI can react.

If you also want the UI to *originate* the action, add an `action` branch in
`Broker.handle_ui_action` (`broker.py`) and wire a button in `index.html`.

## Worked example: task delegation

This is the feature that was added in batch 0, and it touches every part of
the system. Walk through it as a template.

### 1. Broker handler (`broker.py:408-447`)

```python
elif mtype == "task_create":
    if not instance_id:
        continue
    title = (msg.get("title") or "").strip()
    if not title:
        continue
    assignee = msg.get("assignee", "") or ""
    priority = msg.get("priority", "normal")
    deps = msg.get("deps") or []
    async with self.lock:
        tid = self.next_id("T")
        task = {
            "id": tid,
            "title": title,
            "assignee": assignee,
            ...
            "status": "In Progress" if assignee else "Backlog",
            "created_by": instance_id,
            "ts": now_iso(),
        }
        # cycle check on the proposed dep graph
        if self.has_cycle(self.state["tasks"] + [task]):
            ...continue
        self.state["tasks"].append(task)
        self.audit(instance_id, "task_create", f"{tid} -> {assignee or 'unassigned'}")
        self.schedule_write()
    if assignee and assignee != instance_id:
        await self.send_to_instance(assignee, {
            "type": "task_assigned", "task": task,
        })
    await self.state_update({"tasks": self.state["tasks"]})
```

Key observations:

- Always guard with `if not instance_id: continue` — pre-register messages
  are dropped.
- Mutations happen inside `async with self.lock:` to keep concurrent
  handlers from corrupting state.
- Use `self.next_id(prefix)` for stable monotonic IDs.
- Always call `self.audit(...)` and `self.schedule_write()` after every
  mutation. The write debounces, so spamming this is cheap.
- Push to the assignee with `self.send_to_instance(...)`. It returns
  `False` if the assignee is offline; the payload is auto-queued in
  `self.backlog[assignee]` and flushed at next registration.
- Push a `state_update` so the UI redraws the kanban board.

The matching completion branch lives at `broker.py:475-496`:

```python
elif mtype == "task_done":
    ...
    creator = t.get("created_by")
    if creator and creator != instance_id and creator != "you":
        await self.send_to_instance(creator, {
            "type": "task_completed",
            "task": t,
        })
    await self.state_update({"tasks": self.state["tasks"]})
```

Note the symmetry: the *creator* gets a callback when their task is done,
mirroring the `task_assigned` that went to the assignee.

### 2. Client helpers (`connect.py:175-196`)

```python
def broker_task_create(title: str, assignee: str = "", priority: str = "normal",
                       deps: Optional[list] = None):
    """Create a task. If `assignee` is another instance id, they get task_assigned."""
    _schedule(_send_json({
        "type": "task_create",
        "title": title,
        "assignee": assignee,
        "priority": priority,
        "deps": list(deps or []),
    }))


def broker_task_done(task_id: str, result: str = ""):
    _schedule(_send_json({"type": "task_done", "id": task_id, "result": result}))
```

Helpers are deliberately thin — just JSON wrappers around `_send_json`.
Type-checking is the broker's job.

### 3. Incoming-event formatter (`connect.py:66-71`)

The client also gets nice formatting for events the broker pushes:

```python
if t == "task_assigned":
    task = payload.get("task", {})
    return f"[TASK ASSIGNED] {task.get('id', '?')} \"{task.get('title', '')}\" (by {task.get('created_by', '?')})"
if t == "task_completed":
    task = payload.get("task", {})
    return f"[TASK COMPLETED] {task.get('id', '?')} done by {task.get('done_by', '?')}: {task.get('result', '')}"
```

This is purely cosmetic but matters in the REPL — each new event type should
have a one-line readable representation.

### 4. UI event

Task changes use the generic `state_update` channel (`broker.py:447`), which
the UI listens for and re-renders the kanban tab from. For a *novel* event
type that the UI should treat specially, push a typed event:

```python
await self.broadcast_ui({"type": "task_assigned", "task": task})
```

…and add a corresponding `case "task_assigned":` in `index.html`'s WS
handler.

### 5. Registration replay (`broker.py:270-281`)

Because a task can be assigned while the assignee is offline, the broker
also sends a fresh `tasks_init` on every register:

```python
my_tasks = [t for t in self.state["tasks"]
            if t.get("assignee") == instance_id
            and t.get("status") not in ("Done", "Cancelled")]
try:
    await ws.send(json.dumps({
        "type": "tasks_init",
        "tasks": my_tasks,
        "ts": now_iso(),
    }, default=str))
```

Any new event type that has "you might miss it while disconnected"
semantics should follow this pattern. The two existing examples are
`memory_init` and `tasks_init`; the per-instance `backlog` covers the
general case for plain `message`-typed traffic.

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
- [ ] Add `broker_flummox(...)` helper in `connect.py`
- [ ] Add a formatter case in `_fmt_incoming` if the broker echoes the
      event back
- [ ] If the action can fire while the target is offline, replay on
      register (`memory_init` / `tasks_init` precedent)
- [ ] Add a test in `tests/test_broker.py`

## Tests

`tests/test_broker.py` runs the broker on alternate ports (18765/18766) so
it's safe alongside a live broker. The two patterns to copy:

- `make_instance_ws(...)` — opens an instance WebSocket and registers
- `make_ui_ws(...)` — opens a UI WebSocket and reads the init payload

Most tests assert a round trip: instance sends message → broker echoes to
UI / second instance / persistence file. Keep new tests in that shape.
