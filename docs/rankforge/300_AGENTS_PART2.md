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
