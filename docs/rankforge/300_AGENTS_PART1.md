# RANKFORGE + AGENT MESH — 300 AGENT SYSTEM
# The complete, self-sustaining automation engine
# Part 1 of 2: Agents 001–150
# Paste both parts into Claude Code: "Build all 300 agents. Run until the system is fully operational."

---

## MISSION STATEMENT

This is not a tool that finishes. It is a system that runs forever.

Once started, these 300 agents work in continuous loops — crawling, writing, publishing, distributing, monitoring, communicating, learning, and improving — with zero human input required after setup. Every agent that finishes its job checks for more work. Every error triggers a recovery agent. Every success triggers the next step. The system gets smarter over time through the Learning agents that analyze what's working and adjust what isn't.

The human's only job: paste a URL. After that, the agents handle everything.

---

## INFRASTRUCTURE (applies to all 300 agents)

```typescript
// Every agent extends this. Non-negotiable.
abstract class AgentBase {
  abstract id: string           // snake_case, unique across all 300
  abstract name: string         // Human readable
  abstract group: number        // 1-30
  abstract version: string      // semver, starts at "1.0.0"

  // Core lifecycle
  abstract run(input: AgentInput): Promise<AgentOutput>
  abstract nextAgents(output: AgentOutput): AgentTrigger[]
  abstract canRun(input: AgentInput): Promise<boolean>  // pre-flight check

  // Inherited behaviors
  execute(input)    // wraps run() with logging, error handling, retry
  retry(n, delay)   // exponential backoff retry
  cache(key, ttl)   // Redis cache check before running
  log(event)        // structured logging to Supabase
  emit(event, data) // pub/sub to AgentBus
  store(result)     // persist to agent_runs table
  notify(msg)       // send to dashboard + email if critical
}
```

```sql
-- Extended agent infrastructure tables

create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  agent_id text not null,
  agent_version text,
  site_id uuid,
  status text,           -- queued|running|success|failed|skipped|retrying
  attempt int default 1,
  input jsonb,
  output jsonb,
  error text,
  duration_ms int,
  tokens_used int,       -- OpenAI token tracking
  api_calls jsonb,       -- {openai: N, dataforseo: N, bing: N}
  triggered_by text,     -- agent_id | 'user' | 'cron' | 'system'
  triggered_agents text[],
  created_at timestamptz default now(),
  completed_at timestamptz
);

create table agent_messages (
  id uuid primary key default gen_random_uuid(),
  from_agent text,
  to_agent text,          -- specific agent or 'broadcast'
  site_id uuid,
  message_type text,      -- task|status|data|error|query|response
  payload jsonb,
  priority int default 5, -- 1 (highest) to 10 (lowest)
  delivered boolean default false,
  read_at timestamptz,
  created_at timestamptz default now()
);

create table agent_memory (
  id uuid primary key default gen_random_uuid(),
  site_id uuid,
  agent_id text,
  memory_type text,       -- learned|context|preference|pattern|error
  key text,
  value jsonb,
  confidence float,       -- 0.0-1.0
  source text,            -- which run produced this
  expires_at timestamptz,
  created_at timestamptz default now()
);

create table agent_tasks (
  id uuid primary key default gen_random_uuid(),
  site_id uuid,
  assigned_to text,       -- agent_id
  assigned_by text,       -- agent_id or 'user'
  title text,
  description text,
  input jsonb,
  priority int,
  status text default 'pending',
  due_by timestamptz,
  completed_at timestamptz,
  result jsonb,
  created_at timestamptz default now()
);

create table agent_learning (
  id uuid primary key default gen_random_uuid(),
  agent_id text,
  site_id uuid,
  pattern_type text,      -- success|failure|optimization|correlation
  pattern text,
  evidence jsonb,
  applied boolean default false,
  impact_measured float,
  created_at timestamptz default now()
);
```

---

## GROUP 1: GRAND ORCHESTRATION (001–010)

### 001 — Grand Orchestrator
**ID**: `grand_orchestrator`
**Runs**: Continuously. Entry point for all site operations.
**Loop**: Every 60s, scan all sites for work to do. Never stops.
**Core logic**: 
- Pull sites ordered by: urgency × plan_tier × days_since_last_run
- For each site: check what phase it's in, dispatch appropriate agents
- Track: how many agents are currently running (cap at 50 concurrent per instance)
- Respect: user-set pauses, billing limits, rate limits
- Self-heals: if any critical sub-orchestrator goes down, restart it
**Memory**: Keeps running state in Redis (which agents are active per site)
**Never stops running**. If it crashes, a watchdog process (separate cron) restarts it within 60s.

---

### 002 — Site State Machine
**ID**: `site_state_machine`
**Purpose**: Every site moves through defined states. This agent enforces valid transitions.
**States**:
```
new → crawling → analyzing → keyword_research → content_planning → 
generating → publishing → live → monitoring → optimizing
```
And the loop: `live → generating (new content) → publishing → live`
**On invalid transition**: reject + alert GrandOrchestrator
**Stores**: current state + history in Redis per site
**Emits**: state_change events to all subscribed agents

---

### 003 — Quality Gatekeeper
**ID**: `quality_gatekeeper`
**Runs**: After every content generation event
**Checks**: 30-point quality rubric (word count, keyword placement, FAQ presence, readability, schema, internal links, AI-giveaway phrases, factual accuracy estimate, structural integrity, CTA presence)
**Scoring**: Each check weighted. Min score to pass: 75/100
**On fail**: Dispatches ContentReviserAgent with specific failure list
**On pass**: Dispatches PublisherRouter
**Tracks**: Pass rate over time → feeds into PromptOptimizerAgent
**Never publishes substandard content**

---

### 004 — Error Cascade Handler
**ID**: `error_cascade`
**Runs**: Continuously, listens on error channel of AgentBus
**Purpose**: Prevent one agent failure from killing the whole pipeline
**Logic**:
- Classify error (transient|permanent|rate_limit|auth|data|unknown)
- Transient: retry with backoff (30s, 2m, 5m, 15m, stop)
- Rate limit: queue for later (respects window)
- Auth: pause site pipeline + notify user immediately
- Data: try alternate data source, log, continue
- Unknown: retry once, then isolate and continue without this agent
- Tracks: error patterns across sites → feeds ErrorPatternAgent

---

### 005 — Priority Arbitrator
**ID**: `priority_arbitrator`
**Runs**: Every 30s
**Purpose**: Manage the global job queue. Higher plans get more CPU time.
**Logic**:
- Agency plan: 40% of capacity
- Pro plan: 30% of capacity
- Starter plan: 20% of capacity  
- Free plan: 10% of capacity
- Within same plan: manual > scheduled > cron
- Prevents starvation: free tier gets at least 1 job slot always
- Rebalances dynamically when usage spikes

---

### 006 — Dependency Graph Manager
**ID**: `dependency_manager`
**Purpose**: Tracks which agents depend on which. Prevents agents running before inputs are ready.
**Maintains**: Live DAG (directed acyclic graph) of agent dependencies per active pipeline
**Before dispatching any agent**: walk the graph, confirm all upstream outputs exist in Supabase
**Detects**: Circular dependencies (throw + alert immediately)
**Provides**: `getReadyAgents(site_id)` — returns list of agents whose dependencies are satisfied right now

---

### 007 — Resource Governor
**ID**: `resource_governor`
**Purpose**: Never blow past API budgets or rate limits
**Tracks in Redis** (rolling windows):
- OpenAI: tokens/minute, requests/minute, cost/day per site
- DataForSEO: credits/month per account
- Bing WMT: URL submissions/day per site (limit: 100)
- Upstash: commands/second
**On limit approach (>80%)**: slow down dispatch, warn GrandOrchestrator
**On limit hit (100%)**: pause related agents, queue jobs for next window
**Reports**: daily cost summary to admin dashboard

---

### 008 — Agent Health Monitor
**ID**: `health_monitor`
**Runs**: Every 2 minutes
**Checks**: For every registered agent — is it responding? Last successful run? Failure rate?
**Metrics per agent**:
- Success rate (last 100 runs)
- Avg duration
- P95 duration
- Error breakdown by type
**Alerts**: If any agent has >20% failure rate in last hour
**Self-heals**: Marks degraded agents, GrandOrchestrator routes around them
**Dashboard**: Live agent health grid (green/yellow/red per agent)

---

### 009 — Human Bridge
**ID**: `human_bridge`
**Purpose**: The only agent that talks directly to users. All human communication goes through here.
**Handles**:
- Approval requests (pauses pipeline, emails user, waits for response)
- Alerts (sends immediately via email + in-app)
- Weekly digests (assembled from reporting agents)
- Onboarding messages
- Billing warnings
**Response tracking**: Each email has a unique token. User clicks a link → token resolves → pipeline resumes
**Never sends more than 3 emails/day per user** (batches non-urgent items)

---

### 010 — System Clock
**ID**: `system_clock`
**Purpose**: The heartbeat. Triggers all scheduled/recurring agents.
**Runs**: Every minute (cron)
**Checks**: content_calendar, scheduled_tasks, recurring_jobs tables
**Dispatches**: Due jobs to appropriate agents via GrandOrchestrator
**Handles**: Timezone-aware scheduling (per-site timezone setting)
**Prevents**: Double-dispatch (uses Redis lock per scheduled job)
**Also triggers**: End-of-day summaries, weekly reports, monthly audits

---

## GROUP 2: CRAWL & DEEP ANALYSIS (011–022)

### 011 — Site Crawler
**ID**: `site_crawler`
**Trigger**: New site, weekly re-crawl, manual
**Depth**: Up to 3 levels, max 100 pages (free: 25, starter: 50, pro/agency: 100)
**Respects**: robots.txt, crawl-delay directives, rel="nofollow"
**Handles**: JS-rendered sites via Puppeteer/Browserless
**Outputs per page**: URL, status, HTML, response_time_ms, redirect_chain
**Realtime**: Updates crawl_progress via Supabase Realtime every 5 pages

---

### 012 — HTML Deep Parser
**ID**: `html_parser`
**Per-page extraction**:
- All meta tags (title, description, robots, canonical, og:*, twitter:*, hreflang)
- Heading hierarchy (H1-H6) with text + depth
- All images (src, alt, width, height, lazy-load, format)
- All links (internal/external, anchor text, rel attributes, HTTP status)
- Schema markup blocks (parse + validate JSON-LD)
- Word count, paragraph count, sentence count, avg sentence length
- Reading level (Flesch-Kincaid calculation)
- Inline styles vs external CSS ratio
- Script count + render-blocking detection
- Hidden content (display:none, visibility:hidden) — flag for SEO risk

---

### 013 — Technical SEO Auditor
**ID**: `technical_auditor`
**Checks** (40 total, scored weighted):
SSL, mixed content, redirect chains (301→301→301), redirect loops,
sitemap existence + validity + coverage, robots.txt syntax,
canonical consistency, hreflang pairs (if multilingual),
duplicate titles (site-wide), duplicate descriptions,
missing titles, missing descriptions, multiple H1s, missing H1,
image alt coverage %, broken internal links, broken external links (sample),
orphan pages (no inbound links), pagination signals,
mobile viewport meta, AMP pages (detect),
schema syntax validity, schema coverage by page type,
page speed proxy score, resource count,
lazy loading adoption rate, next/prev pagination

---

### 014 — JavaScript SEO Analyzer
**ID**: `js_seo_analyzer`
**Purpose**: Many sites render content via JS — Googlebot may not see it
**Checks**:
- Is meaningful content in raw HTML or only after JS runs?
- Are nav links present in raw HTML?
- Are meta tags server-rendered or JS-injected?
- Does the page have a meaningful `<noscript>` fallback?
- Are there dynamic routes that might be uncrawlable?
**Method**: Fetches page twice (with and without JS), diffs critical elements
**Flags**: Content that only exists in JS-rendered version (search engines may miss it)

---

### 015 — Core Web Vitals Estimator
**ID**: `cwv_estimator`
**Purpose**: Estimate LCP, FID, CLS without running Lighthouse (serverless friendly)
**Signals used**:
- LCP proxy: largest image size, hero image load priority, render-blocking resources
- FID proxy: third-party script count, event listener density (from JS analysis)
- CLS proxy: images without dimensions, late-loading ads, dynamic content injection
- TTFB: measured from crawl response time
**Output**: Estimated CWV scores (green/yellow/red) + specific improvement recommendations
**If Lighthouse API key provided**: run actual Lighthouse audit

---

### 016 — Schema Inspector & Validator
**ID**: `schema_inspector`
**Parses**: All JSON-LD, Microdata, and RDFa on every page
**Validates against**: Schema.org spec for each detected type
**Checks**: Required properties, property types, nested entity correctness
**Detects**: Invalid schema that would fail Google Rich Results test
**Maps**: Which schema types are present vs required for this site's niche
**Output**: Schema inventory + validation report + missing schemas list

---

### 017 — Content Quality Analyzer
**ID**: `content_quality`
**Per-page analysis**:
- Thin content detection (< 300 words for content pages)
- Keyword stuffing detection (>3% density)
- Duplicate content across own site (similarity scoring)
- Content freshness (estimate from visible dates, byline, news signals)
- External links quality (do they link to authoritative sources?)
- Citation presence (are claims backed by sources?)
- E-E-A-T signals (expertise, experience, authority markers)
**Output**: Per-page quality score + issues for ContentImproverAgent

---

### 018 — Competitor Intelligence Agent
**ID**: `competitor_intel`
**Trigger**: After ContentFingerprintAgent
**Per competitor** (up to 10):
- Estimated content volume + publish frequency
- Top content topics (AI-estimated)
- Schema usage patterns
- Estimated DA tier
- Content gaps vs client site
- Writing style + tone analysis
- CTA strategy
- Monetization method visible
**If DataForSEO**: Fetch actual organic keyword data per competitor
**Output**: Competitive landscape report + opportunity map

---

### 019 — Site Architecture Mapper
**ID**: `architecture_mapper`
**Purpose**: Map the entire site structure as a graph
**Builds**:
- Sitemap (tree of all discovered pages)
- Internal link graph (which pages link to which)
- Link equity flow (which pages receive the most internal links)
- Hub pages vs leaf pages
- Silo structure (are topics grouped logically?)
- Orphan page list (no inbound internal links)
- Click depth per page (how many clicks from homepage)
**Output**: Architecture map + structural recommendations

---

### 020 — Content Fingerprinter
**ID**: `content_fingerprinter`
**AI agent** — reads all page content and outputs:
- Primary niche (specific, 10-20 words)
- Sub-niches (up to 5)
- Content already covered (topics list)
- Content gaps (what's missing)
- Tone of voice profile (5 descriptors)
- Target audience persona (detailed)
- Geographic focus
- Topical authority per cluster (0-10)
- Content maturity level (beginner/intermediate/expert)
- Brand voice fingerprint (for content generation consistency)

---

### 021 — Site Speed Deep Auditor
**ID**: `speed_auditor`
**Checks**:
- Total page weight (HTML + CSS + JS + images)
- Number of HTTP requests
- Render-blocking resources in `<head>`
- Images: format (WebP vs JPEG/PNG), lazy loading, responsive srcset
- CSS: unused CSS estimate, critical CSS inlined?
- JS: async/defer on non-critical scripts, bundle size estimate
- Fonts: Google Fonts load method (link vs @import — @import blocks render)
- Third-party scripts: ad networks, tracking pixels, chat widgets (count + estimated impact)
- Caching: cache-control headers present?
**Recommendations**: Prioritized by impact (fastest wins first)

---

### 022 — Redirect & Canonical Auditor
**ID**: `redirect_auditor`
**Detects**:
- Redirect chains (A→B→C — should be A→C directly)
- Redirect loops (A→B→A — catastrophic)
- 301 vs 302 misuse (302 doesn't pass link equity)
- Canonical tag conflicts (page A canonicals to B, but B canonicals to A)
- Self-referencing canonicals (should be present on all pages, often missing)
- Non-canonical pages receiving internal links
- www vs non-www redirect consistency
- HTTP→HTTPS redirect consistency
**Fixes**: Generates redirect map fix file (for .htaccess or Nginx)

---

## GROUP 3: KEYWORD INTELLIGENCE (023–038)

### 023 — Master Keyword Orchestrator
**ID**: `keyword_orchestrator`
**Purpose**: Coordinates all 15 keyword agents. Ensures no duplicate work, merges results.
**Triggers**: All keyword sub-agents in optimal order
**Deduplicates**: Merges keyword lists from all agents, removes duplicates
**Final output**: Single unified keyword database for the site

---

### 024 — Seed Keyword Extractor
**ID**: `seed_extractor`
**Source**: Existing site content (TF-IDF analysis)
**Finds**: What keywords the site is already targeting (explicitly or implicitly)
**Also**: Extracts from page titles, H1s, meta descriptions (declared keywords)
**Output**: 20-30 seed keywords that represent the site's current keyword profile

---

### 025 — AI Keyword Expander
**ID**: `keyword_expander`
**AI agent**. Takes seeds, generates 50-100 expanded keywords:
- Synonyms and semantic variations
- Broader category terms
- Narrower specific terms
- Related concepts
- Industry-specific terminology
Uses niche context + audience profile from ContentFingerprintAgent

---

### 026 — Long-Tail Mining Agent
**ID**: `longtail_miner`
**For each seed keyword**, generates:
- 5 long-tail variations (3-5 words)
- 3 question variations
- 2 comparison variations
- 2 local variations (if location present)
**Total**: 300-500 long-tail keywords from 20 seeds
**These are the easiest rankings to get** — prioritized for quick wins

---

### 027 — Question Keyword Miner
**ID**: `question_miner`
**Generates**: 50 question keywords customers actually ask
**Formats**: How to, What is, Why does, When should, Can I, Is it safe, How much, Which is better, What's the difference
**Source**: AI + People Also Ask patterns for the niche
**Value**: Questions = FAQ content = AI answer inclusion

---

### 028 — Local SEO Keyword Agent
**ID**: `local_keyword_agent`
**If location detected**: generates geo-targeted keywords
- [service] in [city]
- [service] near me (high intent)
- [service] [city] [state]
- best [service] [city]
- [service] [neighborhood]
- [service] [zip area]
- emergency [service] [city]
- [service] [city] open now
- [service] [city] cost/price/rates
**Also**: nearby cities within 30mi radius

---

### 029 — Competitor Keyword Gap Agent
**ID**: `competitor_gap`
**Compares**: Site's covered keywords vs competitor topics
**Finds**: Keywords competitors likely rank for that site doesn't cover
**Prioritizes**: By (competitor volume estimate) × (site's ability to compete)
**Output**: Gap keywords tagged with which competitor dominates them

---

### 030 — Search Intent Classifier
**ID**: `intent_classifier`
**For each keyword**: assigns primary intent
- Informational → blog post / how-to guide
- Commercial → comparison / review
- Transactional → service page / product page
- Navigational → skip (not a content opportunity)
- Local → local landing page
- Question → FAQ article
**Also assigns**: content_type_recommendation + schema_recommendation

---

### 031 — Keyword Difficulty Scorer
**ID**: `difficulty_scorer`
**Scoring factors**:
- Keyword length (longer = easier, generally)
- Brand dominance in likely results (harder)
- Commercial intent (more competitive)
- Question format (generally easier)
- Local modifier (significantly easier)
- Geographic competition (big city = harder)
**With DataForSEO**: Real difficulty score 0-100
**Without**: AI-estimated difficulty with confidence score

---

### 032 — Volume Estimator
**ID**: `volume_estimator`
**With DataForSEO**: Real monthly search volume
**Without API**: AI estimates volume tier (low/medium/high) based on:
- Topic popularity signals
- Industry size
- Question specificity
- Geographic population (for local keywords)
**Output**: Volume estimate + confidence level

---

### 033 — Topical Cluster Builder
**ID**: `cluster_builder`
**Groups**: All keywords into pillar + supporting topic clusters
**Each cluster**:
- 1 pillar keyword (highest volume, broadest)
- 5-15 supporting keywords (long-tail, related)
- Cluster theme name
- Completion percentage (how many posts exist)
- Priority score (based on coverage gap + volume)
**Outputs**: Cluster map used by ContentStrategyAgent

---

### 034 — Seasonal Keyword Detector
**ID**: `seasonal_detector`
**Identifies**: Keywords with strong seasonal patterns
**For each**: Month when search peaks
**Action**: Surfaces seasonal keywords 6-8 weeks before peak
**Examples**: "furnace tune-up" (October), "air conditioner maintenance" (April), "holiday gift" (November)
**Adjusts**: Content calendar timing accordingly

---

### 035 — Trending Keyword Spotter
**ID**: `trend_spotter`
**Monitors**: Industry news + niche trends
**Detects**: Emerging keywords before they peak (early mover advantage)
**Sources**: AI knowledge + recent news if search tool available
**Alert**: When high-opportunity trending keyword detected for a site's niche

---

### 036 — Voice Search Optimizer
**ID**: `voice_optimizer`
**Generates**: Conversational, voice-search-optimized keyword variants
- "Hey Google, [query]" format
- Natural language questions
- "Near me" variants
- Short, direct answer targets
**Why**: Voice search is 20%+ of searches. AI assistants use voice-search patterns.

---

### 037 — People Also Ask Miner
**ID**: `paa_miner`
**For each primary keyword**: generates likely PAA questions
**These appear**: In Google's "People Also Ask" boxes
**Value**: Answering PAA questions = featured snippets + AI answers
**Output**: PAA list → feeds QuestionMiner + FAQGeneratorAgent

---

### 038 — Keyword Performance Tracker
**ID**: `keyword_tracker`
**Continuously**: Tracks which keywords have been targeted (has a post)
**Updates**: `is_used` field when posts published
**Monitors**: Which targeted keywords appear to be gaining traction (via GSC if connected)
**Reports**: Keyword coverage % per cluster to WeeklyReportAgent

---

## GROUP 4: CONTENT CREATION ENGINE (039–060)

### 039 — Content Strategy Planner
**ID**: `content_planner`
**Weekly trigger**. Plans the next batch of content:
- Selects keywords from priority queue (respects monthly post limit)
- Balances: cluster completion vs spreading
- Sequences: pillar first, then supporting
- Applies: seasonal timing, trending topics
- Outputs: Ordered content brief queue for BlogPostWriterAgent

---

### 040 — Master Blog Post Writer
**ID**: `blog_writer`
**The core content agent**. Produces 800-3000 word SEO-optimized posts.

**System prompt (condensed)**:
```
Expert content writer for [niche]. Write for [audience].
Rules: Direct answer in first 2 sentences. Never "As an AI". 
Keyword in title + first 100 words + 2 H2s minimum.
Structure: H1 → TL;DR → intro (direct answer) → sections → FAQ (8 Q&As) → CTA.
Use [INTERNAL_LINK: slug] placeholders. Use [IMAGE: alt text] placeholders.
Return markdown only.
```

**Generates**: title, meta_title, meta_description, slug, full_content_markdown
**Streams**: Output via OpenAI streaming API, displayed word-by-word in UI

---

### 041 — How-To Guide Writer
**ID**: `howto_writer`
**Specialized for**: Step-by-step instructional content
**Structure**: Prerequisites → Materials → Numbered steps → Tips → When to call professional
**Schema**: Auto-generates HowTo schema from step structure
**Each step**: Name (≤20 chars) + detailed instruction (2-5 sentences) + optional warning/tip

---

### 042 — Listicle Writer
**ID**: `listicle_writer`
**Specialized for**: "[N] Best/Ways/Tips/Tools" format posts
**Each item**: H3 + 200-400 words + pro tip
**Total**: 7-25 items depending on word count target
**Comparison table**: Auto-generated for "Best X" listicles

---

### 043 — Comparison Article Writer
**ID**: `comparison_writer`
**For**: "X vs Y", "Best X for Y", "X alternatives"
**Structure**: Verdict upfront → comparison table → deep dive each option → who should choose what → final recommendation
**Schema**: Generates Product schema if comparing products

---

### 044 — Local Landing Page Writer
**ID**: `local_page_writer`
**For**: City/service combination pages
**Must include**: City name, neighborhood references, local signals, NAP data
**Schema**: LocalBusiness with full address + geo coordinates + service area
**Min length**: 800 words of locally-unique content (not just keyword swaps)

---

### 045 — FAQ Article Writer
**ID**: `faq_article_writer`
**For**: Pure FAQ format content
**Structure**: 15-25 question-answer pairs, grouped by sub-topic
**Each answer**: Direct 1-sentence answer + 2-4 sentence elaboration
**Schema**: FAQPage schema auto-generated
**Best for**: Voice search + AI answer inclusion

---

### 046 — Case Study Writer
**ID**: `case_study_writer`
**Structure**: Challenge → Approach → Solution → Results → Key Takeaways
**Tone**: Specific, number-driven, credible
**Uses**: Hypothetical but realistic scenarios if no real cases provided
**Note to user**: "Customize with your actual client data for maximum impact"

---

### 047 — Press Release Writer
**ID**: `press_release_writer`
**Triggers**: New product/service, milestone, community news, seasonal
**Format**: Standard inverted pyramid press release
**Includes**: Who, What, When, Where, Why, Quote from "owner"
**Distribution list**: Generates list of local PR submission sites

---

### 048 — Email Sequence Writer
**ID**: `email_writer`
**For**: Lead nurture sequences, welcome series, promotional campaigns
**Sequence**: 5-7 email series per campaign
**Each email**: Subject line (3 variants) + preview text + body
**Connects**: Blog content to email CTA (drives traffic back to SEO content)

---

### 049 — Video Script Writer
**ID**: `video_script_writer`
**For**: YouTube SEO + embedded video content
**Output**: Full script + B-roll notes + CTA
**Lengths**: Short (60s), Medium (5-8min), Long (15-20min)
**YouTube SEO**: Optimized title, description, tags, chapters, pinned comment
**Bonus**: Generates YouTube schema for video pages

---

### 050 — Podcast Episode Planner
**ID**: `podcast_planner`
**For**: Sites with podcasts (or planning one)
**Output**: Episode title, description (SEO-optimized), show notes, transcript outline, guest questions (if interview format)
**SEO**: Podcast episode schema, transcript for indexing

---

### 051 — Infographic Content Writer
**ID**: `infographic_writer`
**Output**: Data points, statistics, flow steps formatted for infographic design
**Sections**: 5-8 visual sections with headers + key points
**Sources**: AI-estimated statistics with caveats + "verify before publishing" flag
**Bonus**: Alt text for the infographic + transcript for SEO

---

### 052 — Glossary Page Builder
**ID**: `glossary_builder`
**Purpose**: Builds comprehensive industry glossary (great for topical authority + featured snippets)
**Per term**: 50-150 word definition + related terms + example
**Target**: 50-100 terms per glossary
**Schema**: DefinedTermSet + DefinedTerm schema
**Structure**: Alphabetical with anchor navigation

---

### 053 — Resource Page Creator
**ID**: `resource_page_creator`
**Purpose**: Curated list of tools/resources in the niche
**Value**: Highly linkable (others link to resource pages)
**Structure**: Categories → Resources → Brief description + URL
**Note**: AI generates structure; user verifies + adds real URLs
**Link magnet**: One of the best link-building assets

---

### 054 — Product Description Writer
**ID**: `product_description_writer`
**For**: E-commerce or service-specific pages
**Each description**: Title + hook + benefits (bullet) + specs + CTA
**SEO**: Unique descriptions (no manufacturer copy)
**Schema**: Product schema with name, description, offers, aggregateRating placeholder

---

### 055 — Knowledge Base Article Writer
**ID**: `kb_writer`
**For**: Support/documentation content
**Structure**: Problem statement → Solution (numbered steps) → Visual description → Related articles
**Tone**: Clear, concise, technical as needed
**Benefit**: Reduces support tickets + builds topical authority

---

### 056 — Content Refresher
**ID**: `content_refresher`
**Trigger**: Posts older than 6 months, or flagged by RankTrackerAgent as declining
**Updates**:
- Adds current year to title where appropriate
- Updates outdated statistics
- Adds new sections for topics that emerged since publication
- Refreshes internal links to newer posts
- Re-runs QualityGatekeeper before republishing
**Marks**: Updated timestamp in schema and post metadata

---

### 057 — Content Expander
**ID**: `content_expander`
**Trigger**: Posts under 800 words that are ranking but not converting
**Expands**: Adds depth to thin sections, more FAQ questions, more examples
**Target**: Bring post to 1200+ words minimum
**Maintains**: Original structure and rankings-relevant sections

---

### 058 — Content Merger Agent
**ID**: `content_merger`
**Detects**: Multiple short posts on same topic (content cannibalization)
**Action**: Merge into one comprehensive pillar post
**Handles**: 301 redirects from old URLs to new combined URL
**Updates**: Internal links pointing to old URLs

---

### 059 — Title A/B Tester
**ID**: `title_ab_tester`
**Generates**: 5 title variants per post
**Scoring**: CTR potential formula (power words + numbers + keyword placement + urgency)
**If GSC connected**: Tests actual titles by comparing CTR over 30 days
**Winner**: Applied to post after testing period

---

### 060 — Content Calendar Manager
**ID**: `calendar_manager`
**Maintains**: Rolling 90-day content calendar
**Schedules**: Posts evenly (no bunching), avoids same-day publication
**Respects**: Seasonal timing, trending topics, plan limits
**Visualizes**: Calendar view in dashboard with drag-rescheduling
**Triggers**: PostSchedulerAgent for each calendar entry

---

## GROUP 5: ON-PAGE SEO AUTOMATION (061–073)

### 061 — Meta Tag Optimizer
**ID**: `meta_optimizer`
**Runs on**: Every new post + existing pages flagged by audit
**Generates**:
- title tag: keyword-first, compelling, ≤60 chars
- meta description: keyword included, 130-155 chars, CTR-optimized
- og:title, og:description, og:image
- twitter:card metadata
**Validates**: Character counts, keyword inclusion, uniqueness site-wide

---

### 062 — Heading Restructurer
**ID**: `heading_restructurer`
**Fixes**: Heading hierarchy issues (multiple H1s, skipped levels, keyword-poor H2s)
**Generates**: Optimized heading structure with keywords naturally integrated
**Outputs**: Before/after comparison + CMS-specific implementation instructions

---

### 063 — Schema Markup Generator
**ID**: `schema_generator`
**Generates complete JSON-LD for**:
- Article (all blog posts)
- FAQPage (all posts with FAQ sections)
- HowTo (step-by-step posts)
- LocalBusiness (homepage, location pages)
- Organization (homepage)
- WebSite with SearchAction (homepage)
- BreadcrumbList (all pages)
- Product (e-commerce)
- Review/AggregateRating
- Service
- Event (if event content)
- VideoObject (if video embedded)
**Validates**: Against Schema.org spec before output

---

### 064 — Internal Link Optimizer
**ID**: `internal_link_optimizer`
**For all published posts**:
- Finds anchor text opportunities (topic mentions without links)
- Matches to existing posts on that topic
- Suggests: "add link from [post A, phrase X] to [post B]"
**Prioritizes**: Links that improve cluster connectivity
**Prevents**: Over-linking to same page (max 2 links from any one post to any one destination)

---

### 065 — Image SEO Optimizer
**ID**: `image_seo`
**For every image on site**:
- Generate descriptive alt text (if missing or "image.jpg")
- Recommend file name (keyword-based, hyphenated)
- Flag non-WebP images
- Flag missing width/height attributes
- Flag uncompressed large images
**Auto-applies**: Alt text on WordPress via WP REST API if credentials present

---

### 066 — URL Structure Optimizer
**ID**: `url_optimizer`
**Audits**: All URLs for SEO best practices
**Flags**: Underscores (use hyphens), numbers-only slugs, dates in URLs (bad for evergreen), stop words, overly long URLs (>60 chars), session parameters
**For new posts**: Generates clean slug (keyword-first, no stop words, hyphenated)
**Never changes live URLs without user confirmation** (301 redirect required)

---

### 067 — Canonical Tag Manager
**ID**: `canonical_manager`
**Sets**: Self-referencing canonical on every page
**Fixes**: Canonical conflicts, duplicate content canonical chains
**Handles**: Pagination (first page = canonical, paginated pages not canonical)
**Outputs**: Implementation instructions per CMS

---

### 068 — Structured Snippet Optimizer
**ID**: `snippet_optimizer`
**Targets**: Featured snippet positions for each post
**Techniques**:
- Paragraph snippets: 40-60 word direct answers immediately after relevant H2
- List snippets: Ordered/unordered list within first 200 words of relevant section
- Table snippets: Comparison data in markdown table
**Rewrites**: Intro paragraphs to match Google's preferred snippet format

---

### 069 — FAQ Schema Injector
**ID**: `faq_injector`
**Auto-appends**: FAQPage JSON-LD to every post with FAQ section
**Format**: Exact Schema.org FAQPage format
**Validates**: Before injection (required properties, text limits)
**Injects via**: CMS-specific method (Yoast custom field, Webflow embed, Ghost codeinjection)

---

### 070 — Breadcrumb Builder
**ID**: `breadcrumb_builder`
**For every page**: Generates BreadcrumbList JSON-LD
**Also generates**: HTML breadcrumb navigation markup
**Taxonomy**: Ensures consistent category structure (plumbing posts under Plumbing, not randomly)

---

### 071 — Alt Text Batch Writer
**ID**: `alt_batch_writer`
**Finds**: All images across site missing alt text
**For each**: Generates descriptive, keyword-sensitive alt text
**Applies**: Via WordPress REST API (if WP + credentials)
**Reports**: List of images that need manual alt text application

---

### 072 — Thin Content Improver
**ID**: `thin_content_improver`
**Finds**: Pages < 300 words that should have more content
**For each**: Determines if page type warrants expansion or consolidation
**Action A** (expand): Generates additional content sections to add
**Action B** (consolidate): Flags for ContentMergerAgent
**Action C** (delete + redirect): If page has no value, recommend removal + redirect target

---

### 073 — Page Speed Advisor
**ID**: `speed_advisor`
**Based on SpeedAuditorAgent results**: Generates prioritized fix list
**Per fix**:
- What to do (exact instruction)
- Impact estimate (Low/Medium/High)
- Effort estimate (minutes)
- CMS-specific implementation path
- Before/after score estimate
**Prioritizes**: Highest impact / lowest effort first

---

## GROUP 6: GEO — AI VISIBILITY ENGINE (074–087)

### 074 — GEO Grand Coordinator
**ID**: `geo_coordinator`
**Purpose**: Orchestrates all 14 GEO sub-agents
**Runs**: After every crawl + after every post published
**Maintains**: Running GEO score per site (updates in real-time)
**Goal**: Every site eventually scoring 80+ on AI visibility

---

### 075 — Bing Index Manager
**ID**: `bing_index_manager`
**Submits**: Every new post URL to Bing immediately on publish
**Submits**: Full sitemap weekly
**Checks**: Index status 24h after submission
**Re-submits**: Unindexed posts after 7 days
**Tracks**: Bing index coverage % per site
**Why critical**: ChatGPT browsing + Microsoft Copilot + Bing AI all use Bing's index

---

### 076 — Google SGE Optimizer
**ID**: `google_sge`
**Purpose**: Optimize for Google's AI Overviews (SGE)
**Techniques**:
- Ensure direct answer in first paragraph (SGE pulls this)
- Add "What is [topic]" definition blocks (SGE loves clear definitions)
- Add "Key Takeaways" bulleted summary (SGE summarizes these)
- Ensure content matches E-E-A-T signals
- Add author schema + bio page
**Monitors**: SGE appearance for tracked keywords (if tool available)

---

### 077 — Perplexity AI Optimizer
**ID**: `perplexity_optimizer`
**Purpose**: Get cited in Perplexity AI answers
**Perplexity cites**: Real-time web sources, prioritizes recent + authoritative content
**Optimizations**:
- Ensure pages indexed and accessible (no JS-only content)
- Add clear publication dates (freshness signal)
- Include statistics with citations (Perplexity loves citing stats)
- Structure content for excerpt-ability (quotable paragraphs)
- Ensure HTTPS, fast load, clean HTML

---

### 078 — Entity Recognition Builder
**ID**: `entity_builder`
**Creates**: Clear entity signals for the business
**Entities to establish**: Business name, location, services, staff, history
**Methods**:
- Consistent NAP across all pages
- About page with rich entity description
- Author pages (Person entities)
- Social profile links from homepage (sameAs schema property)
- Wikipedia/Wikidata guidance if applicable
- Google Business Profile optimization guidance

---

### 079 — Citation Bait Creator
**ID**: `citation_bait`
**Creates content AI systems love to cite**:
- Original statistics ("X% of homeowners don't know...")
- Definitive definitions ("What is [term]: [clear 1-sentence definition]")
- Structured comparison tables
- "According to [expert/study]" supported claims
- Specific numbers, dates, facts
**AI systems cite**: Specific, verifiable, well-sourced information
**Generates**: Quotable paragraph blocks formatted for maximum citation likelihood

---

### 080 — Structured Data Completeness Checker
**ID**: `schema_completeness`
**For each schema type detected**: Checks ALL recommended properties (not just required)
**Recommended but often missing**:
- Article: `image`, `author`, `publisher`, `dateModified`
- LocalBusiness: `openingHoursSpecification`, `priceRange`, `aggregateRating`
- FAQPage: Often malformed or missing `@id`
**Generates**: Complete schemas with all recommended fields populated

---

### 081 — E-E-A-T Optimizer
**ID**: `eeat_optimizer`
**Builds**: Experience, Expertise, Authoritativeness, Trustworthiness signals
**Actions**:
- Draft author bio pages (Experience + Expertise)
- Suggest: Add "Written by [name], [credentials]" to all posts
- Suggest: Add external citation links to authoritative sources
- Suggest: Add trust signals to homepage (awards, certifications, years in business)
- Suggest: Add transparent contact information, privacy policy
**Generates**: Author bio content + Author schema

---

### 082 — AI Answer Simulator
**ID**: `ai_simulator`
**Simulates**: What ChatGPT/Claude would answer for each target keyword
**Checks**: Would this site's content be a source?
**Gap analysis**: What's missing to get cited?
**Specific output**: "To be cited for '[keyword]', your content needs: [specific additions]"

---

### 083 — Knowledge Graph Connector
**ID**: `kg_connector`
**Establishes**: Connections to known knowledge graph entities
**Methods**:
- Link to Wikipedia pages for mentioned concepts
- Use Schema.org's `sameAs` to reference Wikidata, LinkedIn, Google Business Profile
- Reference authoritative industry organizations
- Cite government or academic sources where relevant
**AI benefit**: LLMs trust content that connects to known, verified entities

---

### 084 — Reddit Citation Strategist
**ID**: `reddit_strategist`
**Why**: Reddit is one of the most-cited sources by AI systems
**Strategy per post**:
- Identify 3-5 relevant subreddits
- Draft community-native posts (valuable, not promotional)
- Suggest timing (subreddit activity patterns)
- Draft comment contributions that naturally include the URL
**Note**: AI systems massively over-index on Reddit for answers

---

### 085 — Quora Domination Agent
**ID**: `quora_agent`
**For each question keyword**: Draft comprehensive Quora answer
**Quality bar**: Quora answers must be genuinely helpful, not just link drops
**Format**: Direct answer → elaboration → link as "full guide here"
**Volume**: AI systems cite Quora answers constantly

---

### 086 — Wikipedia Signal Builder
**ID**: `wikipedia_agent`
**Checks**: Is the business or niche topic on Wikipedia?
**If yes**: Is the site mentioned as a reference? (Legitimate citations only)
**If no Wikipedia article exists for the niche topic**: Draft outline for user to consider creating
**Wikidata**: Guidance on creating/editing Wikidata entity for the business

---

### 087 — AI Visibility Score Tracker
**ID**: `geo_tracker`
**Weekly**: Re-runs GEO audit, updates score
**Tracks**: Score trajectory over time (chart in dashboard)
**Alerts**: When score drops significantly
**Reports**: GEO score progress to WeeklyReportAgent

---

## GROUP 7: PUBLISHING INFRASTRUCTURE (088–100)

### 088 — Publish Pipeline Coordinator
**ID**: `publish_coordinator`
**Manages**: The full pre-publish → publish → verify → distribute pipeline per post
**Steps it coordinates**:
1. Pre-publish checks (QualityGatekeeper passed? Schema valid? CMS connected?)
2. Dispatch PublisherRouter
3. Wait for publish confirmation
4. Trigger PublishVerifier (5 min delay)
5. Trigger BingSubmitter + GSCSubmitter
6. Trigger SocialSnippetGenerator
7. Update post status throughout
**Never skips steps** — each must succeed before next

---

### 089 — WordPress Publisher
**ID**: `wp_publisher`
**Posts via**: WP REST API v2
**Sets**: title, content (HTML), slug, excerpt, status, meta_title (Yoast/RankMath), meta_description, schema (custom field), categories, tags, featured_image
**Detects**: Active SEO plugin (Yoast vs RankMath vs AIOSEO → uses correct meta field names)
**Handles**: Auth failure → HumanBridge alert, duplicate slug → append -2, media upload errors

---

### 090 — Webflow Publisher
**ID**: `webflow_publisher`
**Posts via**: Webflow CMS API
**Handles**: Rich text conversion (markdown → Webflow rich text JSON format)
**Publishes**: Item + triggers site publish (Webflow draft items don't go live until site published)
**Sets**: All CMS fields including custom SEO fields

---

### 091 — Ghost Publisher
**ID**: `ghost_publisher`
**Posts via**: Ghost Admin API (JWT auth)
**Sets**: title, html, status, slug, meta_title, meta_description, og_title, og_description, twitter_title, codeinjection_head (schema JSON-LD), tags, primary_author
**Handles**: JWT token refresh automatically

---

### 092 — Webhook Publisher
**ID**: `webhook_publisher`
**For**: Any CMS via webhook (Framer, custom backend, Make/Zapier, Notion API)
**Sends**: Configurable JSON payload to user-defined URL
**Security**: HMAC-SHA256 signature header
**Retry**: 3× with exponential backoff on non-200

---

### 093 — Static Site Publisher
**ID**: `static_publisher`
**For**: Sites using GitHub Pages, Netlify, Vercel static sites
**Process**: Generates markdown file with frontmatter → commits to user's repo via GitHub API → triggers deploy
**Requires**: GitHub token + repo path configured

---

### 094 — Manual Export Agent
**ID**: `manual_exporter`
**Formats**: Markdown (with frontmatter), clean HTML, plain text
**Delivers**: Download link via email + stored in Supabase Storage 7 days
**Includes**: Copy-paste instructions for detected CMS

---

### 095 — Featured Image Generator
**ID**: `image_gen`
**Mode 1** (DALL-E 3): Professional blog featured image, no text overlays, niche-appropriate style
**Mode 2** (Unsplash): Searches for relevant free image, stores attribution
**Mode 3** (Placeholder): Generates placeholder data if both APIs unavailable
**Stores**: Image URL + attribution in post record

---

### 096 — Post Verifier
**ID**: `post_verifier`
**Runs**: 5 minutes after publish
**Checks**:
- URL returns 200
- Title matches expected
- Schema markup present in HTML source
- Meta tags present and correct
- Content is publicly visible (not behind login)
**On failure**: Alerts HumanBridge with specific issue + rollback option

---

### 097 — Smart Scheduler
**ID**: `smart_scheduler`
**Determines**: Optimal publish time per site
**Factors**: Niche audience (B2B: Tuesday-Thursday 9am-11am, B2C: varies), timezone, existing content gaps
**Distributes**: Posts evenly, never more than 1 per day per site
**Calendar sync**: Updates content_calendar with confirmed publish times

---

### 098 — Rollback Manager
**ID**: `rollback_manager`
**On request or auto-trigger**: Reverts post to draft in CMS
**Never deletes**: Always draft, never destroy
**Logs**: Rollback reason to audit
**Notifies**: User with reason + link to fix

---

### 099 — Multi-Site Sync Agent
**ID**: `multisite_sync`
**For**: Agency users with multiple sites in same niche
**Shares**: Keyword research, content cluster maps (not actual content)
**Prevents**: Same post title published across multiple sites (duplicate content risk)
**Coordinates**: Content calendar across all sites for one agency user

---

### 100 — CMS Health Monitor
**ID**: `cms_health`
**Weekly**: Checks CMS API credentials still valid
**Checks**: Can still authenticate + post to each connected CMS
**Alert**: 7 days before any API key expiry (where expiry is known)
**Tests**: Dummy draft post + immediate deletion to verify full publish flow

---

## GROUP 8: LINK BUILDING SYSTEM (101–112)

### 101 — Link Building Orchestrator
**ID**: `link_orchestrator`
**Coordinates**: All 11 link building agents
**Strategy**: Adapts to site's DA tier (low DA: directories first, medium DA: content + outreach, high DA: digital PR)
**Never**: Buys links, creates link wheels, uses PBNs — white hat only

---

### 102 — HARO Monitor Agent
**ID**: `haro_monitor`
**If HARO/Connectively account connected**: Monitors journalist queries
**Matches**: Queries to site's niche + expertise areas
**Drafts**: Response pitches (expert quotes, specific data, unique angle)
**Alert**: Sends to user for review (HARO links are high-value)

---

### 103 — Resource Page Linker
**ID**: `resource_linker`
**Identifies**: Sites in niche with resource/links pages
**Qualifies**: Are they still actively maintained? DA > 20?
**Drafts**: Outreach email ("I noticed your resources page at [URL]...")
**Timing**: Reaches out for ResourcePageCreatorAgent's output first (needs a linkable asset)

---

### 104 — Broken Link Builder
**ID**: `broken_link_builder`
**Process**:
1. Identify resource types that commonly go dead in the niche
2. For each published post: find external sites that might have linked to similar dead content
3. Draft polite outreach: "Your link to [dead page] is broken. Our [page] is a great replacement."
**Generates**: Strategy + email templates. User sends manually.

---

### 105 — Competitor Backlink Replicator
**ID**: `backlink_replicator`
**Logic**: If a site linked to competitor, they might link to client too
**Process**:
1. Identify competitor's backlink sources (AI-estimated for common niche link sources)
2. Filter to relevant, achievable targets
3. Draft outreach or self-submission instructions per target
**With DataForSEO**: Fetch actual competitor backlink data

---

### 106 — Testimonial Link Builder
**ID**: `testimonial_linker`
**Strategy**: Offer genuine testimonials to tools/services the site uses
**Process**:
1. Identify tools the site likely uses (based on detected tech stack + niche)
2. Draft testimonial for each
3. Many companies link to testimonials from their customers page
**Low effort, often overlooked** link-building tactic

---

### 107 — Guest Post Prospector
**ID**: `guest_prospector`
**Finds**: 10-20 guest posting opportunities per site
**Qualifies**: Relevance to niche, estimated DA tier, accepting guest posts
**Drafts**: Pitch emails + 3 topic ideas per target
**Sequences**: Follow-up email if no response in 7 days

---

### 108 — Podcast Guest Pitcher
**ID**: `podcast_pitcher`
**Finds**: Podcasts in the niche that have guest interviews
**Drafts**: Pitch highlighting the site owner's expertise
**Why**: Podcast guest appearances → show notes link (high-authority backlink)

---

### 109 — Local Citation Builder
**ID**: `local_citation_builder`
**For local businesses**: Builds consistent NAP citations across the web
**Targets**: Google Business, Bing Places, Apple Maps, Yelp, BBB, Yellow Pages + 10 niche-specific directories
**Ensures**: Exact NAP match across all citations (inconsistency hurts local SEO)
**Generates**: Submission checklist + instruction per directory

---

### 110 — Unlinked Mention Converter
**ID**: `mention_converter`
**Monitors**: Web for business name mentions without a link
**For each**: Drafts polite outreach requesting the link be added
**Prioritizes**: High-DA sites first
**Tracks**: Conversion rate (mentions → links)

---

### 111 — Digital PR Agent
**ID**: `digital_pr`
**Creates**: PR-worthy content (studies, surveys, data visualizations, unique angles)
**Distributes**: To relevant journalists, bloggers, news sites
**Goal**: Earn editorial links from news coverage
**Templates**: Story angles that resonate with local + industry press

---

### 112 — Link Velocity Monitor
**ID**: `link_velocity`
**Tracks**: Rate of new backlinks acquired
**Alerts**: If velocity drops (natural link profile has consistent velocity)
**Alerts**: If velocity spikes unnaturally (could signal spam attack)
**Reports**: Link acquisition trend to WeeklyReportAgent

---

## GROUP 9: LOCAL SEO DOMINANCE (113–122)

### 113 — Local SEO Orchestrator
**ID**: `local_orchestrator`
**Activates**: When site has a physical location or service area
**Coordinates**: All 9 local SEO agents
**Goal**: Dominate local pack + local organic + Google Maps

---

### 114 — Google Business Profile Optimizer
**ID**: `gbp_optimizer`
**Generates**: Optimized GBP description (750 chars, keyword-rich, benefit-focused)
**Recommends**: Categories (primary + secondary), services, attributes
**Content calendar**: GBP posts (weekly) — promotions, tips, events
**Q&A section**: Pre-populates with likely questions + answers
**Note**: Cannot directly edit GBP (no API access) — generates copy/paste content

---

### 115 — Review Request Manager
**ID**: `review_manager`
**Generates**: Review request email sequence (3 emails, non-pushy)
**Templates**: Post-service review request + gentle follow-up
**Platforms**: Google, Yelp, industry-specific (Houzz for contractors, etc.)
**Response templates**: Thoughtful replies to both positive and negative reviews
**Schema**: Keeps AggregateRating schema updated with review counts

---

### 116 — Local Content Generator
**ID**: `local_content_gen`
**Creates**: Locally-relevant content assets
- Neighborhood guide for each service area
- "Best [service] in [city]" resource posts (that rank for local intent)
- Local event roundups (builds community ties + local links)
- "We serve [city]" area pages for each city in service area
**Ensures**: Each page is locally unique (not keyword-swap thin content)

---

### 117 — Service Area Page Builder
**ID**: `service_area_builder`
**For each city in service area**:
- Full local landing page (600-1000 words)
- Unique local angle (something specific to that city)
- LocalBusiness schema with areaServed
- Internal links to main service pages
- CTA with local phone number or contact form

---

### 118 — Local Schema Specialist
**ID**: `local_schema`
**Generates**: LocalBusiness schema with ALL recommended fields:
- name, @type (specific type: Plumber, Restaurant, etc.)
- address (streetAddress, addressLocality, addressRegion, postalCode)
- geo (latitude, longitude)
- telephone, email, url
- openingHoursSpecification (per day)
- priceRange
- areaServed (list of cities/regions)
- hasMap (Google Maps URL)
- sameAs (GBP, Facebook, LinkedIn URLs)

---

### 119 — NAP Consistency Enforcer
**ID**: `nap_enforcer`
**Checks**: Business Name, Address, Phone consistent across:
- All site pages
- Schema markup
- Directory listings (generates checklist)
**Flags**: Any inconsistency (even formatting differences matter: "St." vs "Street")
**Generates**: Canonical NAP to use everywhere

---

### 120 — Local Rank Tracker
**ID**: `local_rank_tracker`
**Tracks**: Rankings for [service + city] keywords
**If DataForSEO**: Real local SERP positions
**Without**: AI-estimated rank bracket
**Maps**: Local pack presence (is the business showing in the map pack?)
**Reports**: Local rank trends to WeeklyReportAgent

---

### 121 — Review Response Writer
**ID**: `review_responder`
**Generates**: Personalized responses to reviews
**Positive**: Thank + reinforce service + subtle keyword inclusion
**Negative**: Acknowledge + apologize + offer resolution + professional tone
**Templates**: Parameterized by reviewer name, issue type, service type
**Never**: Defensive, dismissive, or keyword-stuffed

---

### 122 — Local Competitor Analyzer
**ID**: `local_competitor`
**For each local competitor**:
- Review count and rating comparison
- GBP completeness comparison
- Schema usage
- Local content volume
- Estimated citation count
**Output**: Where client can win vs. each competitor + action plan

---

## GROUP 10: E-COMMERCE & PRODUCT SEO (123–132)

### 123 — E-Commerce SEO Orchestrator
**ID**: `ecom_orchestrator`
**Activates**: When CMS detected as Shopify, WooCommerce, or similar
**Specializes**: Product-focused SEO strategy vs. service business strategy

---

### 124 — Product Description Optimizer
**ID**: `product_optimizer`
**For each product page**:
- Unique, SEO-optimized description (not manufacturer copy)
- Benefit-led + feature-detailed structure
- Long-tail keyword integration
- Product schema with name, description, image, offers, availability

---

### 125 — Category Page SEO Builder
**ID**: `category_seo`
**Adds**: 200-400 word introductory content to category/collection pages
**Includes**: Category schema, internal links to subcategories and featured products
**Optimizes**: Category page title + meta + H1 for primary category keyword

---

### 126 — Product FAQ Generator
**ID**: `product_faq`
**Per product/category**: Generates 5-10 product-specific FAQs
**Questions**: Shipping, returns, sizing, compatibility, quality, comparison
**Schema**: FAQPage on product pages (rare — strong ranking signal)

---

### 127 — Collection Schema Generator
**ID**: `collection_schema`
**Generates**: ItemList schema for collection/category pages
**Lists**: Top 5-10 products as ListItem with positions
**Benefit**: Can trigger rich results for collection pages

---

### 128 — Price & Inventory SEO Handler
**ID**: `inventory_seo`
**Checks**: Out-of-stock products with traffic
**Strategy A**: Keep page, note "out of stock", keep internal links, redirect if discontinued
**Strategy B**: If product returning, keep with "Back Soon" + email capture
**Prevents**: Dead pages with no products hurting SEO via index bloat

---

### 129 — Review Schema Aggregator
**ID**: `review_schema`
**Aggregates**: Customer reviews into AggregateRating schema
**Updates**: Schema markup automatically as new reviews come in
**Displays**: Star ratings in search results (high CTR boost)

---

### 130 — Cross-Sell Content Creator
**ID**: `crosssell_content`
**Creates**: "Best [product] to pair with [product]" content
**Purpose**: Internal linking + long-tail traffic + lower bounce rate
**Schema**: ItemList of recommended products

---

### 131 — Seasonal E-Commerce Content Agent
**ID**: `seasonal_ecom`
**Creates**: Holiday gift guides, seasonal sale content, event-based content
**Timing**: 6-8 weeks before seasonal peak
**Covers**: Black Friday, Christmas, Mother's Day, Back to School, etc. (niche-appropriate)

---

### 132 — Breadcrumb & Navigation SEO Agent
**ID**: `navigation_seo`
**Optimizes**: Site navigation for both users and crawlers
**Ensures**: Every product/category reachable within 3 clicks from homepage
**Generates**: BreadcrumbList schema for all category/product levels
**Checks**: Navigation links in raw HTML (not JS-only)

---

## GROUP 11: TECHNICAL CONTENT DELIVERY (133–142)

### 133 — Content Delivery Network Advisor
**ID**: `cdn_advisor`
**Checks**: Is site behind a CDN?
**Detects**: Cloudflare, Fastly, AWS CloudFront headers
**If no CDN**: Recommends + provides setup instructions for Cloudflare (free)
**CDN benefits**: Speed (CWV) + security + reliability

---

### 134 — Hreflang Manager
**ID**: `hreflang_manager`
**For multilingual sites**:
- Validates all hreflang tags
- Checks bidirectional confirmation (en page must reference es, es must reference en)
- Detects: missing x-default, incorrect language codes
- Generates: correct hreflang markup for every page pair

---

### 135 — Pagination SEO Handler
**ID**: `pagination_handler`
**Checks**: Blog pagination (/page/2, /page/3)
**Ensures**: rel="canonical" not pointing to page 1 for paginated pages
**Ensures**: rel="next" and rel="prev" where appropriate
**Prevents**: Pagination pages cannibalizing pillar content

---

### 136 — Log File Analyzer
**ID**: `log_analyzer`
**If log file access provided** (uncommon but powerful):
- Which pages does Googlebot crawl most?
- Which pages are being crawled but provide no value?
- What's the crawl budget usage pattern?
- Are there crawl errors Googlebot encounters?
**Output**: Crawl budget optimization recommendations

---

### 137 — XML Sitemap Manager
**ID**: `sitemap_manager`
**Generates**: Complete, valid XML sitemap for the site
**Includes**: All indexable pages (excludes noindex, admin, duplicate)
**Maintains**: Image sitemap (for image SEO)
**Submits**: To Google Search Console + Bing Webmaster Tools on update
**Updates**: Automatically when new posts published

---

### 138 — Robots.txt Optimizer
**ID**: `robots_optimizer`
**Checks**: Current robots.txt syntax and directives
**Ensures**: Not accidentally blocking important content
**Ensures**: Crawl budget not wasted on admin/checkout/cart pages
**Adds**: Sitemap reference
**Generates**: Optimized robots.txt content

---

### 139 — Security Headers SEO Agent
**ID**: `security_headers`
**Checks**: HTTP security headers (from crawl response)
**SEO-relevant**: HTTPS (critical), HSTS, Content-Security-Policy (can block resources)
**Trust signals**: Proper security headers = trust signals for AI + users
**Recommendations**: What to add + how (varies by hosting)

---

### 140 — AMP Handler
**ID**: `amp_handler`
**Detects**: If site has AMP pages
**Checks**: AMP validity (common errors: invalid CSS, disallowed elements)
**If AMP abandoned or broken**: Recommends proper canonical handling
**If no AMP**: Evaluates whether AMP would benefit (news sites, mobile-heavy)

---

### 141 — Open Graph Optimizer
**ID**: `og_optimizer`
**For every page**: Ensures complete Open Graph metadata
- og:title, og:description, og:image (specific dimensions per platform)
- og:type (article, website, product)
- og:url (canonical URL)
- Article-specific: og:published_time, og:modified_time, og:author
**Why**: OG data is used by LinkedIn, Facebook, Slack previews — improves click-through when shared

---

### 142 — Twitter/X Card Optimizer
**ID**: `twitter_card`
**Generates**: twitter:card metadata for all pages
- summary_large_image for blog posts (higher engagement)
- summary for other pages
- twitter:title, twitter:description, twitter:image
**Validates**: Image dimensions (must be ≥ 300x157px for large card)

---

## GROUP 12: DISTRIBUTION NETWORK (143–150)

### 143 — Distribution Orchestrator
**ID**: `distribution_orchestrator`
**After each post publishes**:
1. Generates social snippets (all platforms)
2. Drafts Reddit posts (relevant subreddits)
3. Drafts Quora answers (relevant questions)
4. Drafts LinkedIn content
5. Drafts Medium article version
6. Queues all for user review or auto-sends (if user enables)

---

### 144 — Twitter/X Content Writer
**ID**: `twitter_writer`
**Generates per post**:
- 3 tweet variants (hook, stat-lead, question-lead)
- Thread outline (10-tweet thread version)
- Reply hook (for engaging in niche conversations)
**Scheduling**: Suggests optimal posting times per niche

---

### 145 — LinkedIn Content Writer
**ID**: `linkedin_writer`
**Generates per post**:
- LinkedIn post (250-400 words, conversational, value-first)
- LinkedIn article (adapted version, 500-800 words, canonical to original)
- Carousel script (6-slide key points)
**B2B focused**: Adapts tone to professional context

---

### 146 — Pinterest Content Creator
**ID**: `pinterest_creator`
**For applicable niches** (home improvement, food, fashion, wellness, etc.):
- Pin title (keyword-rich, 100 chars)
- Pin description (500 chars, keywords + hashtags)
- Board suggestions
- Alt text for pin image
**Visual**: Describes ideal pin image for design

---

### 147 — Medium Syndication Agent
**ID**: `medium_syndicator`
**Adapts**: Blog post for Medium format
**Adds**: canonical link to original post (SEO credit stays with original)
**Identifies**: Relevant Medium publications to submit to
**Format**: Medium-compatible markdown import format

---

### 148 — Reddit Content Drafter
**ID**: `reddit_drafter`
**For each post**: Drafts native Reddit content
**Identifies**: Relevant subreddits (AI estimates from niche)
**Drafts**: Community-appropriate post (adds value, not spam)
**Timing**: Estimates best posting times per subreddit
**Tracks**: Which subreddits drive the most referral traffic (over time)

---

### 149 — Quora Answer Drafter
**ID**: `quora_drafter`
**For each question keyword**: Drafts comprehensive Quora answer
**Length**: 400-700 words (comprehensive answers rank in Quora search)
**Link placement**: Natural, value-first, link as "full guide" not as the main point
**Tracks**: Answer views → traffic contribution

---

### 150 — Newsletter Content Generator
**ID**: `newsletter_gen`
**Weekly**: Compiles published posts into newsletter format
**Format**: Brief intro + post summaries + CTAs back to site
**Platforms**: Mailchimp, ConvertKit, Klaviyo compatible templates
**Drives**: Direct traffic + email engagement signals
```
