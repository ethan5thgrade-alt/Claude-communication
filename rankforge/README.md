# RankForge — Groups 1 & 2

A working TypeScript implementation of agents **001–022** of the 300-agent
RankForge SEO automation system (full spec in
[../docs/rankforge/](../docs/rankforge/)).

- **Group 1 (001–010)** — Grand Orchestration: orchestrator, state machine,
  quality gate, error classifier, priority arbitrator, dependency DAG,
  resource governor, health monitor, human bridge, system clock.
- **Group 2 (011–022)** — Crawl & Deep Analysis: BFS crawler, HTML parser,
  technical SEO auditor, JS-SEO analyzer, CWV estimator, schema inspector,
  content-quality analyzer, competitor intel, architecture mapper, content
  fingerprinter, speed auditor, redirect auditor.

The other 26 groups build on top.

## What's here

```
rankforge/
├── src/
│   ├── core/                  # Shared infra
│   │   ├── AgentBase.ts       # Abstract class every agent extends
│   │   ├── types.ts           # AgentInput / AgentOutput / Site / etc.
│   │   ├── db.ts              # DB abstraction (in-memory fallback)
│   │   ├── redis.ts           # KV + sliding-window + lock primitives
│   │   ├── meshBridge.ts      # Connects each agent to the running Agent Mesh broker
│   │   └── registry.ts        # Agent id → instance lookup
│   ├── agents/group01/
│   │   ├── grandOrchestrator.ts   # 001 — continuous sweep, dispatch by site state
│   │   ├── siteStateMachine.ts    # 002 — enforce valid state transitions
│   │   ├── qualityGatekeeper.ts   # 003 — 10-check rubric, 75/100 to pass
│   │   ├── errorCascade.ts        # 004 — classify + decide retry/alert/giveup
│   │   ├── priorityArbitrator.ts  # 005 — tier-weighted slot allocation
│   │   ├── dependencyManager.ts   # 006 — DAG, cycle detection, ready-set
│   │   ├── resourceGovernor.ts    # 007 — API rate-limit sliding windows
│   │   ├── healthMonitor.ts       # 008 — success-rate + p95 per agent
│   │   ├── humanBridge.ts         # 009 — approval tokens, daily email cap
│   │   ├── systemClock.ts         # 010 — interval + one-shot schedule
│   │   └── index.ts               # registerGroup01() — wires everything
│   └── index.ts                   # entry point (runs orchestrator loop)
├── migrations/
│   └── 001_init.sql           # the 5 infra tables + sites + state history
├── tests/                     # 32 tests across 6 files
└── package.json
```

## Run it

```bash
cd rankforge
npm install
npm test                       # 32/32 should pass
npm start                      # runs the orchestrator loop continuously
```

No external services required — the DB and Redis are in-memory by default.
Wire to real infra by setting env vars:

| Env var                       | Effect when set                                |
|-------------------------------|------------------------------------------------|
| `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | (Stub today, adapter TODO) replace in-memory DB |
| `REDIS_URL`                   | (Stub today, adapter TODO) replace in-memory KV |
| `MESH_BROKER_URL`             | Connect each agent to the Agent Mesh broker so they show in the UI |
| `MESH_TOKEN`                  | Shared-token auth for the mesh                  |

When `MESH_BROKER_URL` is set, every Group-1 agent registers as a mesh
instance — you can watch them in the dashboard at the broker URL,
alongside any Claude Code clients you've also connected.

## What works today

| Agent | Implemented logic | Stubbed |
|---|---|---|
| 001 Grand Orchestrator | sweep loop, ranking, dispatch, capacity cap, self-heal check | — |
| 002 Site State Machine | full state graph + transition validation + history + KV cache | — |
| 003 Quality Gatekeeper | 10-check rubric, scoring, routing to publish/revise | actual content-revision invocation |
| 004 Error Cascade | classifier, retry schedule, alert routing, pattern counters | actual retry dispatch (queues a task) |
| 005 Priority Arbitrator | weighted allocation, starvation prevention, slack redistribution | — |
| 006 Dependency Manager | DAG, cycle detection, ready-set | — |
| 007 Resource Governor | sliding-window hit/check, verdict (ok/slow/paused) | live integration with real APIs |
| 008 Health Monitor | per-agent summary stats, status grading | querying `agent_runs` (needs real DB) |
| 009 Human Bridge | approval tokens, daily cap, deferral | actual SMTP/email send |
| 010 System Clock | due-check, lock, dispatch | persistent cron source |

## Tests

```bash
npm test
```

- `stateMachine.test.ts` — 5 tests
- `errorCascade.test.ts` — 9 tests
- `priorityArbitrator.test.ts` — 5 tests
- `dependencyManager.test.ts` — 6 tests
- `qualityGatekeeper.test.ts` — 3 tests
- `orchestrator.test.ts` — 3 tests
- `node --test` runner, no Jest/Vitest

## Next groups

Groups 2-12 (crawl → keywords → content → publishing) form the data pipeline
that the orchestrator dispatches. Group 13 is already built — it's the
Agent Mesh repo this lives inside. Build out in this rough order:

1. Group 2 (Crawl & Deep Analysis) — produces raw site data
2. Group 3 (Keyword Intelligence) — consumes site data
3. Group 4 (Content Creation Engine) — consumes keyword clusters
4. Group 5 (On-Page SEO Automation) — consumes drafts
5. Group 7 (Publishing Infrastructure) — final step before Quality Gate
6. Groups 14+ as needed (Learning, Monitoring, Reporting, etc.)
