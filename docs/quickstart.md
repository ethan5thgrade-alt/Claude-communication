# Quickstart

A narrative walk-through of going from zero to two Claude Code instances
talking through the broker. Expect this to take ~5 minutes.

## 0. Prerequisites

- macOS or Linux host (this guide uses macOS paths)
- Python 3.10+ — `python3.13` is what the test suite is pinned against
- Two terminal windows (or two tmux panes)

## 1. Install dependencies

```bash
python3 -m pip install --user websockets aiohttp
```

Optional, for running the tests later:

```bash
python3 -m pip install --user pytest pytest-asyncio
```

## 2. Start the broker

In terminal **A**:

```bash
cd ~/agent-mesh
python3 broker.py
```

You should see the startup banner:

```
╔════════════════════════════════════════════════╗
║        AGENT MESH — BROKER RUNNING             ║
╠════════════════════════════════════════════════╣
║ UI:        http://192.168.1.42:8765            ║
║ REST:      http://localhost:8765/api/          ║
║ Instances: ws://localhost:8766                 ║
╠════════════════════════════════════════════════╣
║ Connect snippet:  python connect.py            ║
╚════════════════════════════════════════════════╝
2026-05-17 10:00:01,234 INFO Broker started: UI=8765 instances=8766
```

If the banner doesn't appear, try `python3 -u broker.py` — stdout buffering
can hide the print until the first message arrives.

Leave terminal A running for the rest of the walk-through.

## 3. Open the UI

Open `http://localhost:8765` in your browser (or
`http://<lan-ip>:8765` from your phone if you want to drive it from mobile).
You'll see an empty chat thread on the left, an empty sidebar on the right,
and tabs for MESSAGES / KANBAN / MEMORY / FLOWS / AUDIT across the top.

## 4. Connect the first instance

In terminal **B**:

```bash
cd ~/agent-mesh
python3 connect.py
```

Output:

```
[CONNECTED] cc1 -> ws://localhost:8766
[MEMORY INIT] 0 entries
[TASKS INIT] 0 open task(s) assigned to me
Agent Mesh connect — id=cc1 name=Claude 1 project=OPTFINDER
Commands: send <to> <text...> | broadcast <text...> | status <task...> [|<workload>] | quit
>
```

Back in the UI you should now see a pill labelled "Claude 1" with a green dot
in the sidebar.

## 5. Connect a second instance

Open terminal **C**. Before running, edit `connect.py` so the constants at
the top read:

```python
INSTANCE_ID = "cc2"
NAME = "Claude 2"
PROJECT = "OPTFINDER"
```

(In real use you'd keep a separate `connect.py` per project / repo. For this
walk-through, just rewrite the file or pass overrides via a Python REPL.)

```bash
python3 connect.py
```

```
[CONNECTED] cc2 -> ws://localhost:8766
[MEMORY INIT] 0 entries
[TASKS INIT] 0 open task(s) assigned to me
>
```

The UI sidebar now shows two pills, both green.

## 6. Send your first message

From terminal B (cc1's prompt):

```
> send cc2 hello from cc1
```

In terminal C you should see:

```
[INCOMING from cc1] hello from cc1
```

The UI also shows `[RELAY] cc1→cc2 hello from cc1` in the chat thread.

Try the reverse direction:

```
# terminal C
> send cc1 ack received
```

```
# terminal B
[INCOMING from cc2] ack received
```

## 7. Create a task and hand it off

Drop into Python from terminal B instead of the interactive shell. Kill the
prompt with Ctrl-D, then:

```bash
python3 -i connect.py
```

```python
>>> broker_task_create("Write CSV parser", assignee="cc2", priority="high")
```

In terminal C:

```
[TASK ASSIGNED] T001 "Write CSV parser" (by cc1)
```

The UI's KANBAN tab now shows the task in the "In Progress" column with cc2
as assignee. Mark it done from C:

```python
>>> broker_task_done("T001", result="parser shipped, see commit abc123")
```

Terminal B sees:

```
[TASK COMPLETED] T001 done by cc2: parser shipped, see commit abc123
```

The KANBAN card moves to the "Done" column.

## 8. Write a shared-memory entry

Either instance can publish a fact every other instance (and the UI) will see:

```python
>>> broker_memory("SSE_FORMAT", "{pct, ticker}", mem_type="contract")
```

The UI's MEMORY tab now lists the entry. New instances that register later
receive it in their `memory_init` payload on connect.

## 9. Shut down

`Ctrl-C` each terminal in order: C, B, A. The broker flushes one final
write of `state.json` on shutdown. Re-launching `broker.py` picks up exactly
where you left off.

## Next steps

- [Architecture](./architecture.md) — what the protocol looks like underneath
- [Operations](./operations.md) — running this as a launchd service, log
  paths, health and metrics
- [Extending](./extending.md) — adding new message types
- [Troubleshooting](./troubleshooting.md) — when something doesn't work
