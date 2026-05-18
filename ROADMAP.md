# Agent Mesh — 100-Item Build-Out

Concrete work items grouped into 12 batches. Batches are scoped so each can be
delivered by a single agent in an isolated worktree with minimal conflict.

## Batch 1 — Approval futures (agent-side wait)
1. Broker tracks pending approvals with awaitable futures keyed by ap_id
2. New instance message `approval_request` returns `approval_pending` with ap_id
3. Broker pushes `approval_decision` to the originating instance
4. `connect.py`: `broker_approve_and_wait(action, ...)` returns decision (blocking)
5. Tests: approve-then-resolve, reject-then-resolve, timeout if no decision
6. README: document the new flow with code sample
7. Audit entry records who decided and when
8. UI: approval card shows the asking instance's name + project

## Batch 2 — Flow execution engine
9. Trigger DSL: regex pattern matched against incoming message text
10. Action DSL: `send <to> <template>` and `broadcast <template>` and `webhook <url>`
11. Broker evaluates flows on every persisted message
12. Template variables: `{from}`, `{to}`, `{text}`, `{match.1}` (regex groups)
13. Fire-rate limiter so a flow can't loop indefinitely (max 5/min/flow)
14. Webhook action with timeout + retry-once
15. Tests: regex trigger fires, template renders, rate-limit kicks in
16. UI: flow editor shows trigger pattern preview

## Batch 3 — Vote system (consensus)
17. Agent message `vote_create` with options[]
18. Agent message `vote_cast` with option
19. Auto-resolve when ballots = number-of-online-instances OR threshold reached
20. `broker_vote_create(question, options, threshold)` helper
21. `broker_vote_cast(vote_id, option)` helper
22. `broker_vote_and_wait(question, options)` returns winning option
23. Tests: basic vote, tie handling, threshold trigger
24. UI: live vote tally bars

## Batch 4 — Authentication via shared token
25. `MESH_TOKEN` env var loaded at broker startup
26. Instance WS rejects connections without matching token in register payload
27. UI WS rejects connections without `?token=` query param
28. REST endpoints check `X-Mesh-Token` header
29. `connect.py` reads `MESH_TOKEN` env, includes in register
30. Tests: connect with wrong token → rejected; correct token → accepted
31. README: setup section adds token guidance

## Batch 5 — State schema versioning + migration
32. `schema_version: 2` added to state root
33. Migrator chain `_migrate_v1_to_v2`, runs on load
34. Backup pre-migration state to `state.json.v<n>.bak`
35. Counter integrity check on load (no duplicate IDs)
36. Tests: load v1 state, assert migrated to v2 in-place
37. Daily auto-backup to `state.json.YYYY-MM-DD.bak` (keep last 7)
38. Audit log for migration events

## Batch 6 — mDNS LAN discovery
39. Broker advertises `_agent-mesh._tcp.local` via `zeroconf`
40. `cli.py discover` lists brokers found on LAN
41. `connect.py` falls back to mDNS if BROKER_URL not reachable
42. Service name encodes instance count + version
43. Tests (mock zeroconf): advertise/discover round-trip
44. README troubleshooting for discovery edge cases

## Batch 7 — Launchd auto-start + Makefile
45. `Makefile` with `install-service`, `uninstall-service`, `restart`, `tail-logs`
46. `com.voidlabs.agent-mesh.plist` template with stdout/stderr log paths
47. Logs to `~/Library/Logs/agent-mesh/{out,err}.log`
48. Log rotation via `newsyslog` config snippet
49. `make dev` runs broker with `python3 -u broker.py` for fast iteration
50. README install section adds the launchd workflow

## Batch 8 — Expanded REST API + health/metrics
51. `GET /api/health` returns 200 with uptime, build sha, online-instance count
52. `GET /api/metrics` Prometheus format (msgs/sec, ws connections, backlog size)
53. `GET /api/instances` returns the snapshot
54. `GET /api/tasks` returns all tasks
55. `GET /api/memory` returns memory list
56. `POST /api/task` creates a task (mirrors UI action)
57. `POST /api/memory` writes memory
58. Tests for each new endpoint
59. README REST section expanded

## Batch 9 — TypeScript/JS client
60. `clients/connect.ts` exporting `connectMesh({id, name, project, brokerUrl})`
61. Same surface as Python: send, broadcast, status, taskCreate, taskDone, memory
62. Auto-reconnect with exponential backoff
63. Type definitions for all incoming events
64. `clients/example.ts` showing how to wire into a Node/Bun process
65. README adds a "non-Python clients" section
66. ESM + CJS dual-format build via tsup

## Batch 10 — Tests, CI, pre-commit
67. Expand test_broker.py: vote flow, flow execution, auth, mDNS-mocked
68. Add `tests/test_clients.py` exercising the Python connect.py helpers e2e
69. GitHub Actions `ci.yml`: pytest matrix on 3.10/3.11/3.12/3.13
70. Pre-commit hook config: ruff, black, mypy --strict on broker.py
71. Coverage report uploaded as artifact
72. Add `pytest --benchmark` for the broker message-loop hotpath
73. Smoke test script `scripts/smoke.sh` (spins broker, runs through every API)
74. CONTRIBUTING.md with branch/PR conventions

## Batch 11 — Docs overhaul + architecture
75. `docs/architecture.md` with mermaid sequence diagrams (register, send, relay)
76. `docs/quickstart.md` distinct from README, narrative tutorial
77. `docs/security.md` covering token auth, LAN exposure, data at rest
78. `docs/operations.md` for monitoring/metrics/log paths
79. `docs/extending.md` for new message types, custom flows
80. `docs/troubleshooting.md` (expanded from README)
81. SVG diagrams generated from mermaid via mermaid-cli in Makefile
82. README slimmed to elevator pitch + links to docs/

## Batch 12 — Plugin bridge (claude-code-skills + claude-code-workflows)
83. New instance message `plugin_invoke` with plugin name + tool name + args
84. Broker looks up the plugin in `~/.claude/plugins/cache/<marketplace>/<plugin>/<v>/`
85. Loads the plugin's skill/agent definition and proxies the call
86. Each invocation creates an audit entry
87. `broker_plugin_invoke(plugin, tool, **args)` helper in connect.py
88. UI tab "Plugins" listing installed plugins from both marketplaces
89. UI lets you fire a plugin tool manually
90. README documents the bridge with an apple-hig-expert example
91. Smoke test: invoke `karpathy-coder` review on a sample file
92. Plugin manifest cache to avoid re-reading on every call

## Cross-cutting (last-mile polish)
93. `connect.py`: `broker_log(text, level="info")` writes audit entry without sending to anyone
94. `connect.py`: typed dataclasses for incoming events (improves IDE help)
95. Broker: replace `print(banner)` with rich-style colored output (optional)
96. Broker: graceful shutdown on SIGTERM (flush state, close websockets)
97. State write: switch to fsync on every commit for safety
98. Backlog: cap memory usage with byte budget not entry count
99. Index.html: dark mode toggle, color-blind-safe palette
100. Index.html: keyboard shortcuts (j/k message nav, n new task)
