# RankForge — 300-Agent SEO Automation System

This folder holds the design spec for RankForge, a 300-agent SaaS that
crawls, writes, publishes, distributes, monitors, and learns continuously
once a user pastes a URL. **Agent Mesh** (the repo this folder lives in)
is the communication backbone — Group 13 (agents 151-165) of the spec
maps directly onto the mesh primitives (broker, message routing, task
delegation, memory broadcast, votes, approvals).

## Files

| File | What's in it |
|---|---|
| [`300_AGENTS_PART1.md`](./300_AGENTS_PART1.md) | Agents 001-150 + the infra contract (`AgentBase` class, SQL tables, mission statement) |
| [`300_AGENTS_PART2.md`](./300_AGENTS_PART2.md) | Agents 151-300 (Groups 13-28) |
| [`300_AGENTS_SPEC.md`](./300_AGENTS_SPEC.md) | The two parts concatenated — read this one if you want the whole thing in a single scroll |

## The 28 groups

| # | Group | Agents | Theme |
|---|---|---|---|
| 1 | Grand Orchestration | 001-010 | Continuous loop, state machine, quality gate, error cascade, priority arbitration |
| 2 | Crawl & Deep Analysis | 011-022 | Full-site crawl, content inventory, tech stack detect, performance audit |
| 3 | Keyword Intelligence | 023-038 | Seed expansion, intent classification, SERP analysis, cluster building |
| 4 | Content Creation Engine | 039-060 | Brief → draft → revise → polish, multiple content shapes (blog, FAQ, how-to, comparison) |
| 5 | On-Page SEO Automation | 061-073 | Title/meta/H1, internal linking, schema markup, image alt, canonicals |
| 6 | GEO — AI Visibility | 074-087 | ChatGPT/Perplexity/Claude citation optimization, AI-shoppable formatting |
| 7 | Publishing Infrastructure | 088-100 | WordPress/Shopify/Webflow/Ghost/Framer adapters, scheduling, indexing |
| 8 | Link Building | 101-112 | Outreach, guest-post pitches, broken-link finding, mention monitoring |
| 9 | Local SEO Dominance | 113-122 | GMB optimization, citations, local schema, review monitoring |
| 10 | E-Commerce & Product SEO | 123-132 | Product page, category page, comparison, schema, dynamic pricing pages |
| 11 | Technical Content Delivery | 133-142 | Sitemap, robots, CDN config, Core Web Vitals, render optimization |
| 12 | Distribution Network | 143-150 | Social cross-post, newsletter, syndication, RSS, federated republish |
| **13** | **Agent-to-Agent Communication** | **151-165** | **← This is Agent Mesh: broker, router, discovery, task delegation, memory sync** |
| 14 | Learning & Self-Improvement | 166-178 | Performance analysis, prompt optimization, A/B testing, model selection |
| 15 | Monitoring & Analytics Deep | 179-190 | Rank tracking, traffic attribution, anomaly detection, algorithm radar |
| 16 | Reporting & Communication | 191-200 | Weekly/monthly reports, email, in-app notifications, dashboards |
| 17 | Multi-Language & International | 201-210 | Translation, cultural adaptation, hreflang, multi-country rank tracking |
| 18 | Voice & Conversational Search | 211-218 | Voice-search optimization, position-zero, PAA, question clusters |
| 19 | Video & Multimedia SEO | 219-226 | YouTube, podcast SEO, transcripts, video schema |
| 20 | Social Media Intelligence | 227-234 | Trend detection, share optimization, social proof, viral pattern matching |
| 21 | Conversion Optimization | 235-242 | CRO heuristics, intent matching, CTA placement, exit-intent |
| 22 | Advanced AI Citation Network | 243-252 | Multi-LLM citation tracking, AI overview optimization, training-data prep |
| 23 | Automation Workflow Engine | 253-264 | Custom workflows, triggers, conditional branches, user-defined flows |
| 24 | Security & Content Integrity | 265-272 | Plagiarism check, fact verification, brand-safety, AI-detection-evasion |
| 25 | Infrastructure & Reliability | 273-280 | Auto-scaling, failover, backup, cost monitoring, kill switches |
| 26 | Client & User Management | 281-288 | Billing, plan enforcement, support automation, churn prediction |
| 27 | Advanced Content Intelligence | 289-295 | Topic clustering, content gap analysis, competitive intelligence |
| 28 | Infinite Loop System | 296-300 | Top-level meta-orchestrator, watchdog, self-healing, eternal runtime |

## Infrastructure contract

Every agent extends `AgentBase` (defined in Part 1 §INFRASTRUCTURE) with:
- `run(input) → output`
- `nextAgents(output) → AgentTrigger[]`
- `canRun(input) → bool` (pre-flight)
- Inherited: `execute`, `retry`, `cache`, `log`, `emit`, `store`, `notify`

State lives in 5 Supabase tables: `agent_runs`, `agent_messages`,
`agent_memory`, `agent_tasks`, `agent_learning`. Redis carries the live
state machine.

## Build status

| | |
|---|---|
| **Agent Mesh (Group 13 backbone)** | ✅ Built — this repo (`broker.py`, `connect.py`, `clients/`) |
| RankForge core (other 285 agents) | 📋 Spec only — see the files above |

## Building it out

The mesh covers agent-to-agent comms and task delegation, so the other
groups only need to:
1. Extend `AgentBase` (using the agent-mesh `connect.py` or `clients/connect.ts`)
2. Register with the broker
3. Implement domain logic

A reasonable phasing:
1. Spin up Supabase + Redis
2. Build the `AgentBase` abstract class in TS, wire it to agent-mesh
3. Run the SQL migrations
4. Implement Group 1 (Grand Orchestration) — that gives you the runtime
5. Implement Group 2-7 (the data pipeline: crawl → keywords → content → publishing)
6. Add Group 13 binding to the mesh (mostly already there)
7. Layer Groups 14+ as needed

Order matters because later groups depend on the orchestrator and the
data pipeline being live.
