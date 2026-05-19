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
# RANKFORGE + AGENT MESH — 300 AGENT SYSTEM
# Part 2 of 2: Agents 151–300
# The Communication System, Learning Engine, and Infinite Loop Architecture

---

## GROUP 13: AGENT-TO-AGENT COMMUNICATION SYSTEM (151–165)
*This is what the user originally asked for — the mesh that lets all agents talk.*

---

### 151 — AgentBus Core
**ID**: `agent_bus`
**The message nervous system**. Every agent-to-agent communication goes through here.
**Infrastructure**: Upstash Redis pub/sub + Supabase Realtime
**Channels**:
- `site:{site_id}:all` — broadcast to all agents working on a site
- `agent:{agent_id}` — direct messages to a specific agent
- `group:{group_number}` — messages to all agents in a group
- `priority:critical` — emergency broadcast to all agents system-wide
**Message format**:
```typescript
{
  id: string,
  from: string,        // agent_id or 'system' or 'user'
  to: string,          // agent_id, 'broadcast', or channel name
  type: 'task' | 'data' | 'status' | 'query' | 'response' | 'alert' | 'handoff',
  payload: object,
  priority: 1-10,      // 1 = highest
  ttl: number,         // seconds until message expires
  requires_ack: boolean,
  created_at: string
}
```
**Guarantees**: At-least-once delivery with deduplication
**Throughput**: 10,000 messages/second (Upstash Redis)

---

### 152 — Message Router
**ID**: `message_router`
**Purpose**: Routes every message on AgentBus to correct recipient(s)
**Logic**:
- Direct messages (to: agent_id) → deliver to that agent's queue
- Broadcast → fan-out to all subscribed agents for that site
- Group messages → fan-out to all agents in that group
- Priority escalation → reroute critical messages ahead of queue
**Dead letter queue**: Messages that can't be delivered after 3 attempts → alert + log
**Backpressure**: Slow consumers don't block fast producers

---

### 153 — Agent Discovery Service
**ID**: `agent_discovery`
**Registry**: All 300 agents registered here with capabilities
**API**:
```typescript
getAgent(id: string): AgentCapabilities
findAgentsByCapability(capability: string): Agent[]
getAvailableAgents(site_id: string): Agent[]
getAgentStatus(id: string): 'idle' | 'busy' | 'offline' | 'error'
```
**Use case**: ContentStrategyAgent asks "who can write how-to content?" → gets list of available writers
**Heartbeat**: Agents ping every 30s to stay "online"

---

### 154 — Task Delegator
**ID**: `task_delegator`
**Purpose**: When one agent needs another to do work, it goes through here
**Validates**: Does target agent exist? Is it available? Does it have the capability?
**Creates**: task record in `agent_tasks` table
**Notifies**: Target agent via AgentBus
**Tracks**: Task completion, timeout (alerts if task not completed in expected time)
**Returns**: Result to requesting agent when complete

---

### 155 — Context Synchronizer
**ID**: `context_sync`
**Problem solved**: Multiple agents working on same site need shared context
**Manages**: Shared context object per site in Redis
**Contains**: Current site state, active tasks, recent decisions, shared data
**API**:
```typescript
readContext(site_id): SiteContext
updateContext(site_id, updates): void
subscribeToContext(site_id, callback): Subscription
```
**Ensures**: Agent A's discovery doesn't conflict with Agent B's assumptions

---

### 156 — Handoff Coordinator
**ID**: `handoff_coordinator`
**When agent A finishes and needs to hand to agent B**:
1. A packages its output as a structured handoff object
2. Coordinator validates: output matches B's expected input shape
3. Coordinator delivers to B with full context (what was done, why, what's needed next)
4. B acknowledges receipt
5. A marked complete
**No data loss** between agent transitions

---

### 157 — Broadcast Manager
**ID**: `broadcast_manager`
**Handles**: System-wide broadcasts (all agents, all sites)
**Use cases**:
- Emergency stop: "All agents pause immediately"
- API key updated: "All agents use new OpenAI key"
- Rate limit hit: "OpenAI agents slow down for 60s"
- New feature: "All content agents now include [new element]"
**Delivery guarantee**: All active agents receive broadcast within 2 seconds

---

### 158 — Agent Conversation Logger
**ID**: `conversation_logger`
**Records**: Every agent-to-agent message in `agent_messages` table
**Provides**: Full conversation audit trail
**Query**: "Show me every message exchanged while generating post X"
**Value**: Debugging, improving agent coordination, understanding why decisions were made

---

### 159 — Conflict Resolver
**ID**: `conflict_resolver`
**Detects**: Two agents trying to do contradictory things
**Examples**:
- ContentExpander and ContentMerger both targeting same post
- Two publish attempts for same post simultaneously
- Two agents writing to same schema field
**Resolution**: Priority rules + lock mechanism (Redis locks per resource)
**Logs**: All conflicts resolved for pattern analysis

---

### 160 — Progress Reporter
**ID**: `progress_reporter`
**Collects**: Progress updates from all agents working on a site
**Aggregates**: Into overall pipeline progress percentage
**Pushes**: To dashboard via Supabase Realtime
**Updates**: Every meaningful step (not every second — debounced)
**Shows**: Which agent is currently running, what it's doing

---

### 161 — Agent Memory Manager
**ID**: `memory_manager`
**Manages**: `agent_memory` table — persistent learnings per agent
**Stores**: Patterns, preferences, learned optimizations
**Retrieves**: Relevant memories for an agent before it runs
**Expires**: Stale memories (configurable TTL per memory type)
**Prevents**: Agents re-learning what they already know

---

### 162 — Subscription Manager
**ID**: `subscription_manager`
**Manages**: Which agents subscribe to which AgentBus channels
**Dynamic**: Agents can subscribe/unsubscribe as their task changes
**Efficient**: Agents only receive messages relevant to their current work
**Cleanup**: Auto-unsubscribes agents that go offline

---

### 163 — Event Dispatcher
**ID**: `event_dispatcher`
**Converts**: System events into agent triggers
**Events**:
- `post.published` → trigger BingSubmitter, GSCSubmitter, SocialSnippets
- `crawl.complete` → trigger HTMLParser, TechnicalAuditor
- `score.dropped` → trigger AnomalyDetector, HumanBridge
- `error.critical` → trigger ErrorCascade, HumanBridge
- `user.approved` → resume paused pipeline
**Fully event-driven**: No polling, pure push

---

### 164 — Agent Load Balancer
**ID**: `load_balancer`
**Problem**: Multiple instances of same agent can run (e.g., BlogPostWriter)
**Distributes**: Work across available instances
**Tracks**: Current load per instance (tasks in queue)
**Routes**: New tasks to least-loaded instance
**Auto-scales**: Spins up additional instances when queue > threshold (if serverless)

---

### 165 — Communication Health Monitor
**ID**: `comm_health`
**Monitors**: AgentBus health (message delivery rate, latency, queue depth)
**Alerts**: If message delivery latency > 5s
**Alerts**: If dead letter queue growing (messages failing to deliver)
**Dashboard**: Real-time comm health metrics
**Self-heals**: Restarts AgentBus connections if degraded

---

## GROUP 14: LEARNING & SELF-IMPROVEMENT ENGINE (166–178)

### 166 — Learning Orchestrator
**ID**: `learning_orchestrator`
**The brain that makes the system smarter over time**.
**Weekly**: Aggregates all performance data across all agents, all sites
**Identifies**: What's working, what's not, what's improved
**Distributes**: Learnings to relevant agents via agent_memory
**Updates**: Prompts, priorities, strategies based on evidence

---

### 167 — Content Performance Analyzer
**ID**: `perf_analyzer`
**Tracks**: Every published post's performance over time
**Signals used**:
- GSC: impressions, clicks, CTR, average position
- Traffic estimates: trending up or down
- Engagement estimate: time on page signals
- Conversion: lead/contact form submissions (if trackable)
**Identifies**: What content types, lengths, structures perform best per niche

---

### 168 — Prompt Optimizer
**ID**: `prompt_optimizer`
**Analyzes**: QualityGatekeeper pass rates per content type
**Correlates**: Prompt version → post quality score
**Experiments**: A/B tests prompt variants (10% of generations use experimental prompt)
**Updates**: Winning prompts into the prompt library
**Tracks**: Token efficiency (same quality at lower token cost = saves money)

---

### 169 — SEO Pattern Learner
**ID**: `seo_learner`
**Discovers**: What SEO patterns correlate with better rankings
**Examples**: "Posts with 5+ internal links rank faster", "FAQ sections improve ranking speed by 30%", "Posts over 1500 words outperform shorter posts in this niche"
**Applies**: Learnings to content generation parameters
**Site-specific**: Learns patterns per niche/site type

---

### 170 — Failure Pattern Analyzer
**ID**: `failure_analyzer`
**Analyzes**: All agent failures over rolling 30 days
**Identifies**: Common failure patterns (same error, different sites = system problem)
**Generates**: Fix recommendations for recurring issues
**Alerts**: If failure rate increasing on any agent
**Prevents**: Same failure happening repeatedly without fix

---

### 171 — A/B Test Coordinator
**ID**: `ab_coordinator`
**Runs**: Structured experiments on:
- Title formats (number vs question vs benefit)
- Meta description styles
- Content lengths
- CTA placements
- FAQ section position (top vs bottom)
**Methodology**: 50/50 split, statistical significance at 95%, minimum 30-day test
**Reports**: Results + winning variant applied going forward

---

### 172 — Niche Intelligence Accumulator
**ID**: `niche_intel`
**Builds**: Niche-specific knowledge base over time
**For each niche**: What keywords convert, what content length works, what schema helps most, what seasonality looks like, who the real competitors are
**Shares**: Across all sites in same niche (anonymized)
**Improves**: Every new site in the niche benefits from learnings from all previous sites

---

### 173 — User Behavior Learner
**ID**: `behavior_learner`
**Learns**: Per user — what do they approve vs reject?
**Tracks**: Do they always rewrite titles? Do they prefer longer posts? Do they publish everything or review carefully?
**Adapts**: Generation parameters to match user's revealed preferences
**Reduces**: Back-and-forth between generated content and user preferences

---

### 174 — Quality Trend Tracker
**ID**: `quality_tracker`
**Monitors**: Average QualityGatekeeper score over time per agent
**Alerts**: If average quality dropping (might mean OpenAI model change or prompt drift)
**Benchmarks**: Against baseline quality score from initial deployment
**Reports**: Quality trend in WeeklyReport

---

### 175 — Cost Optimizer
**ID**: `cost_optimizer`
**Tracks**: API costs per site, per agent, per day
**Identifies**: Which operations are most expensive
**Suggests**: Cost-saving alternatives (shorter prompts, caching more aggressively, batching API calls)
**Limits**: Enforces per-site monthly API cost budgets
**Reports**: Cost attribution to admin dashboard

---

### 176 — Speed Optimizer
**ID**: `speed_optimizer`
**Tracks**: How long each agent takes (P50, P95, P99)
**Identifies**: Bottlenecks in the pipeline
**Suggests**: Parallelization opportunities (which agents could run simultaneously but currently run sequentially)
**Implements**: Approved optimizations in pipeline planner

---

### 177 — Model Selector
**ID**: `model_selector`
**Chooses**: Which OpenAI model to use per task
- Complex strategy/analysis → GPT-4o
- Content generation → GPT-4o (quality critical)
- Simple classification/tagging → GPT-4o-mini (cost efficient)
- Schema generation → GPT-4o-mini (structured output)
**Adapts**: Based on quality requirements + cost budget remaining

---

### 178 — Continuous Improvement Engine
**ID**: `improvement_engine`
**Monthly**: Deep review of entire system performance
**Generates**: System improvement recommendations (which agents to upgrade, which prompts need work, which pipelines are inefficient)
**Versions**: Updates agent versions when improvements applied
**Changelog**: Maintains what changed and why (full audit trail)

---

## GROUP 15: MONITORING & ANALYTICS DEEP (179–190)

### 179 — Analytics Orchestrator
**ID**: `analytics_orchestrator`
**Coordinates**: All 11 monitoring agents
**Dashboard**: Aggregates all metrics into the analytics dashboard
**Realtime**: Pushes live updates via Supabase Realtime

---

### 180 — Rank Tracking Engine
**ID**: `rank_engine`
**Tracks**: 50 keywords per site per week (Pro/Agency: unlimited)
**With DataForSEO**: Real SERP positions daily
**Without**: AI-estimated rank brackets weekly
**Trend**: Position over time graph per keyword
**Alerts**: Keywords moving ±5 positions

---

### 181 — Traffic Attribution Model
**ID**: `traffic_attribution`
**Estimates**: Which posts are driving which traffic
**Model**: keyword_position × avg_CTR × keyword_volume = estimated_monthly_visits
**Per post**: Attribution of estimated traffic contribution
**Trend**: Traffic growing or declining per post
**Insight**: "Your top traffic post this month: [title]"

---

### 182 — Conversion Tracking Agent
**ID**: `conversion_tracker`
**If GA4/GTM connected**: Tracks form submissions, calls, purchases from SEO traffic
**Without**: Estimates conversion potential by intent score
**Reports**: Revenue attribution estimate from SEO content

---

### 183 — Competitor Intelligence Monitor
**ID**: `competitor_monitor`
**Bi-weekly**: Re-runs competitor analysis
**Tracks**: Are competitors publishing more? New content topics? Schema changes?
**Alerts**: If competitor starts dominating a keyword cluster the site targets

---

### 184 — Index Health Checker
**ID**: `index_health`
**Weekly**: Verifies all published posts are indexed (Bing + Google)
**For unindexed posts**: Re-submits + alerts if still unindexed after 14 days
**Coverage report**: % of published posts indexed per search engine

---

### 185 — Brand Monitor
**ID**: `brand_monitor`
**Weekly**: Scans for brand name mentions
**Finds**: Unlinked mentions → converts to link opportunities
**Sentiment**: Positive vs negative mention tracking
**Alerts**: Negative mentions that need response

---

### 186 — Backlink Health Monitor
**ID**: `backlink_health`
**Monthly**: Checks backlink profile
**If DataForSEO**: Real backlink data (new, lost, toxic)
**Without**: AI-estimated link profile health
**Toxic links**: Flags spammy links, recommends disavow

---

### 187 — Algorithm Radar
**ID**: `algo_radar`
**Monitors**: Industry SEO news + Google announcements
**Detects**: Correlation between site score changes and known algorithm updates
**Advice**: Specific recovery steps for each update type (core, helpful content, spam, link spam)
**Proactive**: Pre-update hardening recommendations

---

### 188 — Anomaly Detection Engine
**ID**: `anomaly_engine`
**Real-time monitoring**:
- Score drops > 10pts in 24h → alert
- Traffic estimate drops > 20% week-over-week → alert
- Posts de-indexed → alert
- CMS publishing failing → alert
- Site returning 5xx → "site down" alert
**Statistical**: Z-score anomaly detection for gradual declines

---

### 189 — SEO Score Historian
**ID**: `score_historian`
**Stores**: Weekly score snapshots per site
**Provides**: Score trajectory charts for dashboard
**Computes**: Rate of improvement (how many points gained per month)
**Forecasts**: Projected score in 3/6 months at current rate

---

### 190 — Reporting Aggregator
**ID**: `reporting_aggregator`
**Collects**: Output from all monitoring agents
**Formats**: Into structured report data for ReportingGroup agents
**Caches**: Report data for 24h (don't re-run expensive queries for multiple report formats)

---

## GROUP 16: REPORTING & COMMUNICATION (191–200)

### 191 — Report Orchestrator
**ID**: `report_orchestrator`
**Coordinates**: All 9 reporting agents
**Triggers**: Weekly (Monday 8am), monthly (1st of month), on-demand
**Ensures**: Reports sent exactly once (idempotency keys)

---

### 192 — Weekly Report Writer
**ID**: `weekly_writer`
**AI agent**. Writes the weekly email report narrative.
**Inputs**: Score changes, posts published, keywords gained, traffic estimate, anomalies
**Tone**: Encouraging, plain English, no SEO jargon
**Structure**: Big numbers up top → wins → concerns → next week plan → one action item
**Personalized**: References their specific site, niche, posts by name

---

### 193 — Monthly Deep Report Writer
**ID**: `monthly_writer`
**AI agent**. Comprehensive monthly performance report.
**Covers**: Full metric review, content performance ranking, keyword wins, competitor moves, next month strategy
**Format**: PDF-quality HTML email with charts (ASCII or embedded SVGs)

---

### 194 — Email Delivery Agent
**ID**: `email_delivery`
**Sends via**: Resend API
**Templates**: Responsive HTML emails, dark mode compatible
**Tracking**: Open rates + click-throughs via Resend webhooks
**Unsubscribe**: Managed, compliant (CAN-SPAM, GDPR)
**Rate**: Max 3 emails/day per user, non-urgent items batched

---

### 195 — In-App Notification Agent
**ID**: `inapp_notifier`
**Delivers**: Real-time in-app notifications via Supabase Realtime
**Types**: success (post published), warning (score dropped), info (keyword opportunity), error (CMS auth failed)
**Groups**: Multiple notifications in 60s window → single grouped notification
**Actionable**: Each notification has 1 clear action button

---

### 196 — Dashboard Data Publisher
**ID**: `dashboard_publisher`
**Pushes**: Live data to dashboard via Supabase Realtime channels
**Updates**: Score gauges, post status, keyword counts, activity feed
**Debounced**: No more than 1 update per 5s per data type
**Offline**: Queues updates for when user reconnects

---

### 197 — Performance Summary Generator
**ID**: `perf_summary`
**AI agent**. Translates raw metrics into business outcomes.
**Examples**:
- "3 new posts published → estimated 420 additional visitors next month"
- "AI Visibility score: 67 → your business is now appearing in ChatGPT answers for [keyword]"
**Used**: Dashboard header, email reports, onboarding milestones

---

### 198 — Recommendation Publisher
**ID**: `rec_publisher`
**Always-on**. Single most important recommendation surfaced at all times.
**Rotates**: Never same recommendation twice in a row
**Personalizes**: Based on site's current weakest area
**CTA**: Each recommendation has a direct action button

---

### 199 — Milestone Celebrator
**ID**: `milestone_celebrator`
**Detects**: First post published, first indexed page, first 1000 estimated visitors, first AI citation, 90-day score improvement
**Sends**: Celebratory email + in-app notification
**Purpose**: Keeps users engaged through SEO's long feedback loops
**Includes**: What the milestone means in plain English + what comes next

---

### 200 — Client Report Builder
**ID**: `client_report`
**For agency users**: Generates white-labeled client reports
**Customizable**: Agency logo, brand colors, client name
**Format**: Professional PDF-quality HTML
**Data**: All metrics for that specific site only (no cross-client data)
**Delivery**: Email to client directly or download for agency to send

---

## GROUP 17: MULTI-LANGUAGE & INTERNATIONAL (201–210)

### 201 — Language Detection Agent
**ID**: `lang_detector`
**Detects**: Primary language of site content
**Checks**: html lang attribute, content language analysis, hreflang tags
**Downstream impact**: All content generation uses detected language

---

### 202 — Multi-Language Content Coordinator
**ID**: `multilang_coordinator`
**For sites targeting multiple languages**:
- Tracks which posts exist in which languages
- Prioritizes translation of highest-traffic posts first
- Ensures hreflang implementation is correct
- Prevents same content published in two languages on same domain without proper signals

---

### 203 — Content Translator
**ID**: `content_translator`
**Translates**: Blog posts to target languages
**Quality**: Not just machine translation — AI rewrite for natural fluency
**SEO**: Translates with target-language keyword research (not literal translation of English keywords)
**Schema**: Updates language-specific schema markup

---

### 204 — International Keyword Researcher
**ID**: `intl_keyword_researcher`
**For non-English markets**: Researches keywords in native language
**Adapts**: Search behavior differs by country (question formats, formality)
**Local**: Country-specific search trends, local competitors

---

### 205 — Cultural Adaptation Agent
**ID**: `cultural_adapter`
**Ensures**: Content appropriate for target culture (not just translated)
**Flags**: Idioms that don't translate, cultural references that won't land, date/number formats
**Adapts**: Tone (formal vs informal varies massively by language/culture)

---

### 206 — Hreflang Implementation Manager
**ID**: `hreflang_manager`
**Generates**: Correct hreflang tags for every page/language combination
**Validates**: Bidirectional confirmation, x-default, correct ISO codes
**Implements**: Via CMS-specific method

---

### 207 — Local Search Engine Adapter
**ID**: `local_search_adapter`
**Handles**: Markets where Google isn't dominant
- China: Baidu optimization (different signals, Chinese-language schema)
- Russia: Yandex optimization (different ranking factors)
- South Korea: Naver optimization
- Japan: Yahoo Japan considerations
**Adapts**: Strategy per market's dominant search engine

---

### 208 — RTL Content Handler
**ID**: `rtl_handler`
**For**: Arabic, Hebrew, Farsi content
**Ensures**: dir="rtl" attribute on html element
**Checks**: CSS alignment properties work correctly for RTL
**Schema**: Correct language codes (ar, he, fa)

---

### 209 — International Schema Builder
**ID**: `intl_schema`
**Adapts schema for international**:
- Currency in Offers schema (local currency)
- Address format (country-specific)
- Phone format (country code)
- Opening hours (local timezone)

---

### 210 — Multi-Country Rank Tracker
**ID**: `country_rank_tracker`
**Tracks**: Rankings per keyword per country
**Handles**: Geo-targeted search results (keyword ranks differently in UK vs US vs Australia)
**Reports**: Country-by-country performance breakdown

---

## GROUP 18: VOICE & CONVERSATIONAL SEARCH (211–218)

### 211 — Voice Search Optimizer
**ID**: `voice_optimizer`
**Optimizes content for**: "OK Google", "Hey Siri", "Alexa" queries
**Characteristics**: Longer, more conversational, question-format
**Techniques**:
- Conversational answer format (direct, spoken naturally)
- Featured snippet targeting (voice reads the featured snippet)
- "Near me" optimization
- Local business schema (voice often pulls business info)

---

### 212 — Conversational Content Rewriter
**ID**: `conversational_rewriter`
**Takes**: Formal blog content
**Rewrites**: Key sections in natural spoken language
**Use case**: Sections targeted at voice search queries
**Balance**: Document readable AND voice-search-friendly

---

### 213 — Smart Speaker Schema Builder
**ID**: `smart_speaker_schema`
**Schema types** voice assistants use:
- Speakable schema (marks content suitable for text-to-speech)
- LocalBusiness (address, phone, hours — voice pulls this)
- FAQPage (voice reads Q&A directly)
**Generates**: Speakable schema for intro paragraphs

---

### 214 — Position Zero Optimizer
**ID**: `position_zero`
**Targets**: Featured snippets (voice reads position zero)
**Per qualifying keyword**: Rewrites answer sections to 40-60 words (paragraph snippet) or formats as clean list (list snippet)
**Tracks**: Featured snippet wins over time

---

### 215 — People Also Ask Optimizer
**ID**: `paa_optimizer`
**For every PAA question related to target keywords**:
- Ensure a direct answer exists in content
- Answer format matches Google's PAA format (2-3 sentence direct answer)
- These answers get pulled into PAA boxes + voice results

---

### 216 — Conversational AI Content Formatter
**ID**: `conv_ai_formatter`
**Formats content** for maximum AI assistant citation:
- Direct answer in first sentence (AI reads first sentence)
- Definition blocks ("X is defined as...")
- "Key Facts" sections (AI loves bullet facts)
- Step-by-step numbered lists (AI quotes numbered lists)
- Summary paragraphs (AI pulls summaries)

---

### 217 — Question Cluster Builder
**ID**: `question_cluster`
**Builds**: Complete answer hub for every question variant of a topic
**Structure**: One master FAQ page + individual detailed articles per question
**Internal linking**: All question answers link to each other (topic cluster)
**Result**: Site "owns" the question space for a topic

---

### 218 — Natural Language Processor
**ID**: `nlp_processor`
**Analyzes**: Existing content for NLP quality signals
**Checks**: Semantic richness (related terms present?), entity density (named entities), sentiment consistency
**Google's NLP API**: If connected, runs actual NLP analysis
**Improves**: Content based on NLP signals to better match how Google understands topics

---

## GROUP 19: VIDEO & MULTIMEDIA SEO (219–226)

### 219 — Video SEO Orchestrator
**ID**: `video_orchestrator`
**Activates**: When video content detected or planned
**Coordinates**: All video SEO agents

---

### 220 — YouTube SEO Agent
**ID**: `youtube_seo`
**For YouTube-embedded or planned video content**:
- Optimized video title (keyword + benefit)
- Description (first 150 chars keyword-rich, full description for keywords)
- Tags (15-20 relevant tags)
- Chapter timestamps (improves watch time + search features)
- Card and end screen script suggestions
- Pinned comment template

---

### 221 — Video Schema Generator
**ID**: `video_schema`
**Generates**: VideoObject schema for pages with embedded video
**Includes**: name, description, thumbnailUrl, uploadDate, duration, contentUrl, embedUrl
**Benefit**: Video rich results in Google (video thumbnail in SERP)

---

### 222 — Transcript Generator
**ID**: `transcript_gen`
**For YouTube videos**: Pulls transcript (YouTube's auto-captions)
**Formats**: Clean transcript for page content (below video)
**SEO value**: Transcript = 1000+ words of additional indexable content
**Schema**: Adds transcript to VideoObject schema

---

### 223 — Podcast SEO Agent
**ID**: `podcast_seo`
**For podcast episodes** (if site has a podcast):
- Episode title (SEO-optimized)
- Episode description (300-500 words, keyword-rich)
- Show notes (detailed, with timestamps)
- Transcript (for indexing)
- PodcastEpisode schema
- Submit to: Google Podcasts (via RSS), Apple Podcasts, Spotify

---

### 224 — Image SEO Deepdiver
**ID**: `image_seo_deep`
**Beyond alt text**:
- Image file names (keyword-hyphenated.jpg)
- Image sitemap generation
- Image schema (ImageObject, for visual search)
- Responsive image markup (srcset, sizes)
- Lazy loading implementation check
- WebP conversion recommendations

---

### 225 — Media Sitemap Builder
**ID**: `media_sitemap`
**Generates**: Image sitemap + Video sitemap
**Image sitemap**: All images with captions, titles, geographic location if relevant
**Video sitemap**: All video embeds with titles, descriptions, thumbnails
**Submits**: To GSC + Bing Webmaster Tools

---

### 226 — Infographic SEO Agent
**ID**: `infographic_seo`
**For each published infographic**:
- Full text alternative (transcript of infographic content)
- Embed code with attribution (makes infographic shareable = backlinks)
- Image schema with description
- Alt text for the infographic image
- Pinterest optimization (infographics perform excellently on Pinterest)

---

## GROUP 20: SOCIAL MEDIA INTELLIGENCE (227–234)

### 227 — Social Intelligence Hub
**ID**: `social_hub`
**Central controller** for all social media SEO intelligence
**Why social matters for SEO**: Social signals influence E-E-A-T, brand mentions = entity strength, social shares drive initial traffic that generates link opportunities

---

### 228 — Social Listening Agent
**ID**: `social_listener`
**Monitors**: Brand mentions across platforms
**Finds**: Conversations where brand could add value (reply with content link)
**Tracks**: Share counts on published posts
**Sentiment**: Positive/neutral/negative mention tracking

---

### 229 — Hashtag Research Agent
**ID**: `hashtag_researcher`
**Per post**: Generates platform-optimal hashtag sets
- Instagram: 20-30 hashtags (mix of volume sizes)
- Twitter: 2-3 hashtags (fewer = more engagement)
- LinkedIn: 3-5 hashtags (professional, topic-specific)
- TikTok: 5-10 hashtags (niche + trending)

---

### 230 — Viral Pattern Analyzer
**ID**: `viral_analyzer`
**Studies**: What content goes viral in the niche
**Patterns**: Emotional triggers, format types, posting times, headline structures
**Applies**: Learnings to content generation + distribution strategy

---

### 231 — Social Proof Aggregator
**ID**: `social_proof`
**Collects**: Testimonials, reviews, social mentions for use in content
**Generates**: "As seen on" social proof blocks
**Schema**: Aggregates into Review schema
**Maintains**: Library of approved social proof for use across site

---

### 232 — Competitor Social Analyzer
**ID**: `competitor_social`
**Studies**: What competitors post on social
**Finds**: Content gaps (what they're NOT covering)
**Identifies**: Their best-performing content types
**Suggests**: Counter-content + differentiation strategy

---

### 233 — Social Post Scheduler
**ID**: `social_scheduler`
**After each blog publish**:
- Queues social posts across all platforms
- Staggers: Don't post everywhere simultaneously (looks robotic)
- Schedule: Platform-optimal times per niche
- Delivers: Final posts to user for review OR auto-posts if social API connected

---

### 234 — Influencer Identifier
**ID**: `influencer_id`
**Finds**: Key voices in the niche
**Why**: Being mentioned/shared by influencers = authority signals + traffic
**Strategy**: Content that naturally attracts influencer sharing (data, tools, unique angles)
**Outreach**: Draft personalized outreach templates per influencer

---

## GROUP 21: CONVERSION OPTIMIZATION (235–242)

### 235 — CRO Orchestrator
**ID**: `cro_orchestrator`
**Coordinates**: All CRO agents
**Goal**: Turn SEO traffic into leads/sales
**SEO without conversion = vanity metrics**

---

### 236 — CTA Optimizer
**ID**: `cta_optimizer`
**Analyzes**: Current CTAs across all posts
**Generates**: Compelling, relevant CTAs for each content type
**Placement**: In-content (after first H2), mid-page, end of post, sticky header
**A/B tests**: CTA copy variants over time

---

### 237 — Lead Magnet Creator
**ID**: `lead_magnet`
**Creates**: Downloadable assets that capture emails
**Types**: Checklist, template, calculator, guide, cheatsheet
**Format**: Content brief + design description (user creates or commissions design)
**Integration**: Suggests how to embed in high-traffic posts

---

### 238 — Landing Page Analyzer
**ID**: `landing_analyzer`
**Assesses**: Service/product pages for conversion readiness
**Checks**: Headline clarity, benefit statements, social proof, CTA prominence, trust signals, objection handling
**Generates**: Rewrite recommendations for underperforming pages

---

### 239 — Exit Intent Content Suggester
**ID**: `exit_intent`
**Suggests**: Content to show on exit intent overlay
**Personalized**: Based on what content user was reading
**Formats**: Email capture, related post recommendation, offer
**Generates**: Copy for exit intent popup

---

### 240 — Internal Search Optimizer
**ID**: `search_optimizer`
**If site has search**: Analyzes what users search for internally
**Finds**: Content gaps (users searching for things that don't exist)
**Prioritizes**: Most-searched uncovered topics for ContentPlannerAgent

---

### 241 — User Journey Mapper
**ID**: `journey_mapper`
**Maps**: How a visitor moves from landing page → content → conversion
**Identifies**: Drop-off points
**Recommends**: Internal links + CTAs to guide users toward conversion
**Creates**: Optimal content pathways per user intent

---

### 242 — Funnel Content Creator
**ID**: `funnel_creator`
**Creates**: Content for each funnel stage
- TOFU (awareness): educational posts, how-to guides
- MOFU (consideration): comparison posts, case studies, reviews
- BOFU (decision): pricing pages, testimonials, demos, guarantees
**Ensures**: Full funnel covered in content strategy

---

## GROUP 22: ADVANCED AI CITATION NETWORK (243–252)

### 243 — AI Citation Coordinator
**ID**: `citation_coordinator`
**The most important group for future SEO**. AI citations > Google rankings for many queries.
**Coordinates**: All citation-building agents
**Goal**: Get every site appearing in AI answers for their target keywords

---

### 244 — ChatGPT Citation Builder
**ID**: `chatgpt_citation`
**Specifics of getting cited by ChatGPT**:
- ChatGPT browsing uses Bing → prioritize Bing indexing
- ChatGPT favors: authoritative, specific, well-sourced content
- Structure: Direct answers, specific facts, cited statistics
- Recency: ChatGPT favors recently updated content
- Builds: Content structured for ChatGPT response format

---

### 245 — Perplexity Citation Builder
**ID**: `perplexity_citation`
**Perplexity's citation behavior**:
- Real-time web crawl for every query
- Favors: Multiple trustworthy sources confirming same fact
- Heavily cites: Reddit, academic papers, official sources, news
- Strategy: Get cited on Reddit/Quora → Perplexity cites those posts → indirect citation
- Direct citation: Ensure pages accessible, fast, accurate, specific

---

### 246 — Google Gemini Visibility Builder
**ID**: `gemini_visibility`
**Gemini cites**: Google's own index + Google properties first
**Strategy**:
- Google Business Profile optimization (Gemini pulls this)
- YouTube videos (Google-owned, Gemini prioritizes)
- Google Docs shared publicly (indexed)
- Ensure strong E-E-A-T (Gemini's quality signals)
- Author authority (verified Google profiles)

---

### 247 — Claude AI Visibility Builder
**ID**: `claude_visibility`
**Claude's training data sources** (as of knowledge cutoff):
- Common Crawl (vast web index)
- Books + academic papers
- GitHub (technical content)
- Wikipedia
**Strategy**: Get content on high-DA sites Claude was likely trained on. Build Wikipedia citations. Publish on Medium/Substack/LinkedIn (likely in training data). Create well-cited, authoritative content.

---

### 248 — AI Training Data Submitter
**ID**: `training_data_sub`
**Submits to**: Common Crawl opt-in (site gets crawled for inclusion in datasets)
**Partners**: DataCommons, Wikidata (for entity data)
**Academic**: Submit research/studies to academic repositories
**Long-term**: Today's web content becomes tomorrow's AI training data

---

### 249 — Entity Graph Optimizer
**ID**: `entity_graph_opt`
**Builds**: Rich entity relationships in schema markup
**Examples**:
- Business → serves → Location
- Service → has → Price
- Expert → works at → Business
- Business → member of → Association
**Why**: LLMs understand entities + relationships. Rich entity graphs = better AI understanding of what the business is and does.

---

### 250 — AI-Friendly Content Formatter
**ID**: `ai_formatter`
**Applies** to every post before publishing:
- TL;DR block (AI extracts this)
- "What is X" definition block in first H2
- Key statistics prominently displayed
- Numbered lists for processes (AI quotes numbered lists)
- "According to [source]" citation blocks
- Clear entity mentions (business name, location, services stated explicitly)

---

### 251 — Authority Building Agent
**ID**: `authority_builder`
**Builds**: Long-term domain authority (the foundation of all AI citation)
**Strategy**:
- Original research + data (most cited content type)
- Expert roundups (attracts shares + links from quoted experts)
- Industry surveys ("We surveyed 100 [niche] customers...")
- Free tools (calculators, estimators — attract links perpetually)
**Generates**: Content briefs for authority-building assets

---

### 252 — AI Answer Monitor
**ID**: `ai_monitor`
**Weekly**: Tests target keywords in ChatGPT, Perplexity (if API access available)
**Checks**: Is the site cited? Is a competitor cited instead?
**Tracks**: Citation frequency over time
**Reports**: AI citation progress to dashboard

---

## GROUP 23: AUTOMATION WORKFLOW ENGINE (253–264)

### 253 — Workflow Designer
**ID**: `workflow_designer`
**Visual**: Users can design custom automation workflows
**Building blocks**: Trigger → Condition → Action
**Templates**: Pre-built workflows (publish daily, audit monthly, report weekly)
**Saves**: As workflow JSON executed by WorkflowEngine

---

### 254 — Trigger Manager
**ID**: `trigger_manager`
**Handles all workflow triggers**:
- Time-based: cron expressions
- Event-based: post published, score changed, crawl completed
- Threshold-based: score drops below 60, traffic drops 20%
- Manual: user-initiated
- Webhook: external triggers (Zapier, Make, custom)

---

### 255 — Condition Evaluator
**ID**: `condition_evaluator`
**Evaluates**: Workflow conditions before executing actions
**Conditions**: AND/OR/NOT logic
**Examples**: "IF score < 70 AND plan = 'pro' THEN run full audit"
**Supports**: Complex nested conditions

---

### 256 — Action Executor
**ID**: `action_executor`
**Executes**: Workflow actions in correct order
**Actions**: Dispatch any of the 300 agents, send email, create task, update record, call webhook
**Error handling**: Workflow-level error handling (different from agent error handling)

---

### 257 — Loop Handler
**ID**: `loop_handler`
**Manages**: Repeating workflows
**Types**: For-each (run action for each post), while (run until condition met), scheduled repeat
**Prevents**: Infinite loops (max iteration limits + detection)

---

### 258 — Batch Processor
**ID**: `batch_processor`
**Groups**: Similar jobs for efficiency
**Examples**: 
- Batch 50 image alt text generations into one API call
- Batch 10 keyword lookups into one DataForSEO request
- Batch schema validations per site
**Reduces**: API calls by 60-80% via intelligent batching

---

### 259 — Parallel Task Coordinator
**ID**: `parallel_coordinator`
**Identifies**: Tasks that can run simultaneously
**Manages**: Promise.all-style parallel execution
**Limits**: Max parallelism per site (prevents hitting API rate limits)
**Merges**: Results from parallel agents before next sequential step

---

### 260 — Sequential Enforcer
**ID**: `sequential_enforcer`
**Ensures**: Strictly ordered pipelines run in order
**Waits**: For each step to complete before starting next
**Timeout**: Fails gracefully if step exceeds max duration
**Retry**: Re-runs failed steps before failing the sequence

---

### 261 — Workflow Audit Logger
**ID**: `workflow_auditor`
**Logs**: Every workflow execution
**Captures**: Which steps ran, what they produced, how long each took
**Queryable**: "Show me everything that ran for site X yesterday"
**Export**: Audit log as CSV for agency clients

---

### 262 — Cron Job Manager
**ID**: `cron_manager`
**Manages all recurring jobs**:
- Daily: Generate scheduled posts (9am), index check
- Weekly: Full crawl (Sunday 2am), report (Monday 8am), rank check
- Monthly: Deep audit, competitor analysis, link building review
**Handles**: Timezone awareness, DST changes, missed jobs (runs immediately if missed window)

---

### 263 — Webhook Manager
**ID**: `webhook_manager`
**Receives**: External webhooks (user events, third-party triggers)
**Sends**: Outbound webhooks (Zapier, Make, custom endpoints)
**Security**: Validates incoming webhook signatures
**Retry**: Failed outbound webhooks retry 3× with backoff

---

### 264 — Automation Template Library
**ID**: `template_library`
**Maintains**: Library of proven automation templates
**Templates**:
- "SEO Autopilot" (full automation for hands-off users)
- "Content Machine" (generates + publishes on schedule)
- "Quick Win Sprint" (focuses on quick wins for 30 days)
- "GEO Domination" (focused AI visibility campaign)
- "Local SEO Blitz" (local business specific)
**Users**: Pick a template to instantly set up automation

---

## GROUP 24: SECURITY & CONTENT INTEGRITY (265–272)

### 265 — Content Safety Checker
**ID**: `safety_checker`
**Runs before every publish**:
- No personal information accidentally included
- No competitor defamation
- No false health/medical/legal claims
- No misleading pricing claims
- Flags potentially problematic content for human review

---

### 266 — Plagiarism Detector
**ID**: `plagiarism_detector`
**Checks**: Generated content against known sources
**Method**: Key phrase search + similarity scoring
**Threshold**: Flag if >15% similarity to any single source
**Action**: Trigger ContentReviserAgent to rewrite flagged sections

---

### 267 — Brand Voice Enforcer
**ID**: `brand_voice`
**Learns**: Brand voice from existing site content (ContentFingerprintAgent output)
**Checks**: Generated content matches learned brand voice
**Scores**: Tone match, vocabulary match, formality level
**Corrects**: Sections that deviate significantly from brand voice

---

### 268 — Duplicate Content Guardian
**ID**: `duplicate_guardian`
**Site-wide**: Ensures no two posts are too similar
**Threshold**: Flag if two posts are >40% similar
**Action**: Suggest ContentMergerAgent or differentiate the posts
**Prevents**: Internal duplicate content penalty

---

### 269 — Sensitive Topic Handler
**ID**: `sensitive_handler`
**Detects**: Content touching sensitive areas (health, finance, legal, parenting, weight loss)
**YMYL flag**: "Your Money or Your Life" topics require extra care
**Actions**: Add appropriate disclaimers, increase E-E-A-T signals, recommend professional consultation where appropriate
**Never**: Makes medical/legal/financial claims without appropriate caveats

---

### 270 — Copyright Scanner
**ID**: `copyright_scanner`
**Checks**: Are any images used without attribution?
**Checks**: Are long quotes from other sources properly attributed?
**Checks**: Is any content substantially derived from a copyrighted source?
**Action**: Flag for human review before publish

---

### 271 — GDPR Compliance Checker
**ID**: `gdpr_checker`
**For EU-targeting sites**:
- Privacy policy present and up to date?
- Cookie consent mechanism present?
- Contact forms have GDPR consent checkbox?
- Analytics properly anonymized?
**Generates**: Compliance checklist + copy for privacy notices

---

### 272 — Spam Score Analyzer
**ID**: `spam_analyzer`
**Checks**: Would this content be flagged as spam by Google?
**Red flags**: Keyword stuffing, thin content, hidden text, excessive links, automated-feeling text
**Score**: 0-100 spam score (lower = better)
**Action**: Content scoring > 30 goes to ContentReviserAgent

---

## GROUP 25: INFRASTRUCTURE & RELIABILITY (273–280)

### 273 — System Health Dashboard
**ID**: `health_dashboard`
**Real-time**: Shows status of all 300 agents
**Color coding**: Green (healthy), Yellow (degraded), Red (down)
**Metrics**: Success rate, avg response time, queue depth per agent
**Alerts**: Auto-fires if any critical agent goes red

---

### 274 — Database Optimizer
**ID**: `db_optimizer`
**Weekly**: Analyzes Supabase query performance
**Indexes**: Adds missing indexes for common query patterns
**Vacuums**: Suggests maintenance operations
**Partitioning**: Recommends table partitioning for large tables (agent_runs grows fast)

---

### 275 — Cache Warming Agent
**ID**: `cache_warmer`
**Pre-loads**: Common queries into Redis before they're needed
**Warms**: Dashboard data at midnight (so 8am dashboard load is instant)
**Warms**: Keyword lists for sites with content generation scheduled today

---

### 276 — Backup & Recovery Agent
**ID**: `backup_agent`
**Daily**: Exports critical data to Supabase Storage
**Backs up**: All published content (in case CMS loses it), all SEO data, all agent memories
**Recovery**: Can restore any site's SEO state from backup
**Tests**: Monthly recovery test (actually restores from backup, verifies data)

---

### 277 — Deployment Verifier
**ID**: `deploy_verifier`
**After every deployment**:
- Tests all API endpoints (health checks)
- Runs synthetic transaction (fake site crawl + fake post generation)
- Verifies all 300 agents respond to ping
- Alerts immediately if anything broken post-deploy
**Prevents**: Silent failures after deployments

---

### 278 — Cost Tracker & Budget Enforcer
**ID**: `cost_tracker`
**Tracks**: Real-time API costs (OpenAI, DataForSEO, Browserless)
**Per-site budgets**: Enforces monthly API cost limits
**Per-plan caps**: Free tier gets minimal API budget, Agency tier gets maximum
**Alerts**: At 80% and 100% of budget
**Reports**: Cost breakdown to admin dashboard

---

### 279 — Performance Profiler
**ID**: `profiler`
**Profiles**: Every agent execution (time breakdown by sub-operation)
**Identifies**: Slow operations (N+1 queries, unnecessary API calls)
**Reports**: To SpeedOptimizerAgent for improvement
**Benchmark**: Baseline performance metrics stored, alerts on regression

---

### 280 — Multi-Instance Coordinator
**ID**: `instance_coordinator`
**If deployed across multiple servers/regions**:
- Ensures no duplicate jobs run (distributed locks)
- Maintains consistent state across instances
- Coordinates graceful shutdown (finish current jobs before stopping)
- Leader election (one instance is "primary" for certain singleton operations)

---

## GROUP 26: CLIENT & USER MANAGEMENT (281–288)

### 281 — Onboarding Journey Agent
**ID**: `onboarding_agent`
**Day 0**: Welcome email + "here's what happens next"
**Day 2**: "Your first post is ready to publish"
**Day 7**: "Here's your first week results"
**Day 30**: "One month in — here's what we've accomplished"
**Triggers**: Based on actual milestones (not just time)

---

### 282 — Churn Prediction Agent
**ID**: `churn_predictor`
**Signals**: Login frequency dropping, features unused, site score stagnant, no posts published
**Score**: Churn risk 0-100
**Action**: High-risk → trigger HumanBridge for proactive outreach
**Prevents**: Silent churners (users who just stop without canceling)

---

### 283 — Plan Upgrade Suggester
**ID**: `upgrade_suggester`
**Detects**: Users hitting plan limits (posts/month, sites, features)
**Timing**: Suggests upgrade at the moment of value (when they want to do something they can't)
**Message**: Specific ("You've used 5/5 posts this month. Upgrade to Pro for unlimited posts.")
**Never**: Aggressive upselling. Only when genuinely helpful.

---

### 284 — Feature Adoption Tracker
**ID**: `adoption_tracker`
**Monitors**: Which features each user has and hasn't tried
**Prompts**: Gentle feature discovery nudges ("You haven't tried the GEO suite yet — it could increase your AI visibility by 30 points")
**Guides**: In-app tooltips triggered by behavior

---

### 285 — White-Label Configurator
**ID**: `whitelabel_config`
**For agency plan users**:
- Custom logo in UI
- Custom domain (reports.agencyname.com)
- Custom colors in reports
- Agency name in email sender
- Remove RankForge branding from client-facing outputs

---

### 286 — Usage Analytics Agent
**ID**: `usage_analytics`
**Tracks**: Feature usage across all users
**Reports to admin**: Which features are most used, which are ignored
**Feeds into**: Product roadmap decisions
**A/B**: Feature adoption rates for new feature variants

---

### 287 — Support Ticket Generator
**ID**: `support_agent`
**Detects**: User confusion patterns (same action failed 3× = confusion)
**Auto-creates**: Support ticket with full context
**Suggests**: Relevant help docs
**Escalates**: To human support if automated help fails

---

### 288 — Referral Program Manager
**ID**: `referral_manager`
**Tracks**: Referral links + conversions
**Rewards**: Automatic credit/discount for successful referrals
**Generates**: Personalized referral landing pages
**Optimizes**: Referral incentive based on conversion data

---

## GROUP 27: ADVANCED CONTENT INTELLIGENCE (289–295)

### 289 — Trend Content Creator
**ID**: `trend_creator`
**Monitors**: Industry news + trending topics
**Creates**: Timely content pieces on trending topics in the niche
**Speed**: Can generate + publish in < 2 hours when trend detected
**Value**: First-mover advantage on trending keywords

---

### 290 — Content Gap Filler
**ID**: `gap_filler`
**Runs monthly**:
- What questions are people asking in this niche that this site doesn't answer?
- What competitor content gets traffic that this site lacks?
- What cluster topics are incomplete?
**Generates**: Priority list of gap content to create

---

### 291 — Evergreen Content Manager
**ID**: `evergreen_manager`
**Identifies**: Which posts are evergreen (should stay fresh forever)
**Maintains**: Annual refresh schedule for evergreen content
**Adds**: "Last updated [year]" to titles where beneficial
**Protects**: Don't let evergreen posts go stale (schedule regular updates)

---

### 292 — Content Cannibalization Resolver
**ID**: `cannibalization_resolver`
**Detects**: Multiple posts targeting same keyword (splitting ranking signal)
**Resolution options**:
- Merge: Combine into one comprehensive post
- Differentiate: Make each post target a different variation
- Canonicalize: Make one the canonical, others support it
**Implements**: Chosen resolution automatically where possible

---

### 293 — Topical Authority Tracker
**ID**: `topical_authority`
**Measures**: How much of each topic cluster is covered
**Tracks**: Authority building progress per cluster over time
**Target**: 10+ posts per main cluster = strong topical authority
**Guides**: ContentPlannerAgent on where to focus next

---

### 294 — Content ROI Calculator
**ID**: `content_roi`
**Estimates**: Revenue value per post
**Formula**: estimated_traffic × conversion_rate × average_order_value
**Per post**: What's this content worth in estimated monthly revenue?
**Portfolio**: Which posts are highest ROI? Create more like them.

---

### 295 — Predictive Content Planner
**ID**: `predictive_planner`
**AI agent**. Uses 6-12 months of data to predict:
- Which keywords will become more valuable
- What content types will outperform
- When to publish what (seasonal timing optimization)
- What competitors will likely do next
**Plans**: Content strategy 90 days ahead based on predictions

---

## GROUP 28: INFINITE LOOP SYSTEM (296–300)
*These agents never stop. They keep the entire system running forever.*

---

### 296 — Eternal Monitoring Agent
**ID**: `eternal_monitor`
**Runs**: Every 5 minutes, forever
**Checks**: Is every site in the system being actively worked on?
**Finds**: Sites that haven't had any agent activity in 48h
**Action**: Re-triggers SiteStateMachine for dormant sites
**Ensures**: No site ever gets abandoned by the system

---

### 297 — Content Velocity Maintainer
**ID**: `velocity_maintainer`
**Goal**: Every site publishes at least N posts per month (N = plan tier)
**Checks**: Daily — is current month's publish rate on track?
**If behind**: Accelerates content generation (shortens queue wait times, generates multiple posts in parallel)
**If ahead**: Normal pace
**Never**: Lets a site miss a month with zero content

---

### 298 — Improvement Loop Runner
**ID**: `improvement_loop`
**Weekly infinite loop**:
1. Measure: Collect all performance metrics
2. Analyze: What improved? What degraded? Why?
3. Hypothesize: What change would improve results?
4. Experiment: Implement change for 10% of traffic/content
5. Measure experiment
6. If better: Roll out to all. If worse: Revert.
7. Repeat from step 1

**This loop makes the system permanently self-improving**

---

### 299 — Cross-Site Learning Distributor
**ID**: `cross_site_learner`
**The network effect agent**. Every new site makes all sites better.
**Collects**: What's working across ALL sites (anonymized)
**Distributes**: Learnings to improve strategies for all sites
**Examples**:
- "HowTo posts in home services niche get 3× more featured snippets"
- "Posts published Tuesday rank faster in this niche"
- "FAQ sections added 45% to AI citation rate for service businesses"
**Applies**: Automatically to all new content generation

---

### 300 — The Infinite SEO Engine
**ID**: `infinite_engine`
**The master loop that never ends**:

```
LOOP FOREVER:
  for each site in system:
    current_score = get_score(site)
    target_score = 100
    
    if current_score < target_score:
      gaps = identify_gaps(site)
      for each gap:
        dispatch_agents_to_close_gap(gap)
    
    content_needed = calculate_content_deficit(site)
    if content_needed > 0:
      generate_and_publish_content(site, content_needed)
    
    run_monitoring_suite(site)
    run_geo_optimization(site)
    run_distribution_suite(site)
    update_scores(site)
    report_to_user(site)
  
  learn_from_all_results()
  improve_all_agents()
  
  sleep(3600)  // Wake up every hour and do it again
```

**This is the vision**: A system that never stops working. Every hour, it looks at every site, finds every gap, fills every gap, and makes every site better. Automatically. Forever. With no human input required after the initial URL.

**Human's only job**: Review the weekly report and decide if they want to redirect strategy.

---

## FINAL IMPLEMENTATION DIRECTIVE

### How to build this:

**Step 1** — Build the infrastructure (AgentBase, AgentBus, AgentRegistry, all DB tables)
**Step 2** — Build Group 1 (Grand Orchestration) — this is the skeleton
**Step 3** — Build Group 13 (Agent Communication) — this is the nervous system
**Step 4** — Build Groups 2-3 (Crawl + Keywords) — this is the senses
**Step 5** — Build Group 4 (Content Creation) — this is the hands
**Step 6** — Build Groups 5-7 (On-Page, GEO, Publishing) — this is the delivery system
**Step 7** — Build Groups 8-12 (Link, Local, Ecom, Technical, Distribution) — these are the amplifiers
**Step 8** — Build Groups 14-16 (Learning, Monitoring, Reporting) — this is the brain feedback loop
**Step 9** — Build Groups 17-27 (all specialized agents) — these are the specialists
**Step 10** — Build Group 28 (Infinite Loop) — this is the heartbeat

### The system is complete when:
- All 300 agents are registered in AgentRegistry
- Agent 001 (GrandOrchestrator) can coordinate all 300
- Agent 296 (EternalMonitor) runs without stopping
- Agent 300 (InfiniteEngine) runs its loop on all sites every hour
- A new user can paste a URL and receive their first published blog post within 90 minutes, automatically, without touching anything
- 30 days later, they receive a weekly report showing X new posts published, Y keywords now ranking, Z points score improvement — all with zero additional input

**Build until this works. Run until it's perfect. Loop until it can't be improved.**
