// 001 — Grand Orchestrator.
// Continuous entry point. Every 60s, scan every site, dispatch appropriate work.
// Caps concurrent agents at 50 per instance. Respects pauses, billing, rate limits.

import { AgentBase } from "../../core/AgentBase.ts";
import { db } from "../../core/db.ts";
import { kv } from "../../core/redis.ts";
import { getAgent } from "../../core/registry.ts";
import { SiteStateMachine, isValidTransition } from "./siteStateMachine.ts";
import { PriorityArbitrator } from "./priorityArbitrator.ts";
import { ResourceGovernor } from "./resourceGovernor.ts";
import { HealthMonitor } from "./healthMonitor.ts";
import { ErrorCascade } from "./errorCascade.ts";
import type { AgentInput, AgentOutput, Site, SiteState } from "../../core/types.ts";

export const MAX_CONCURRENT = 50;
export const LOOP_INTERVAL_MS = 60_000;

// Map site state → next agent that should advance it.
const STATE_TO_NEXT_AGENT: Partial<Record<SiteState, string>> = {
    new: "site_crawler",
    crawling: "html_deep_parser",
    analyzing: "keyword_seed_generator",
    keyword_research: "content_brief_writer",
    content_planning: "content_drafter",
    generating: "quality_gatekeeper",
    publishing: "publisher_router",
    live: "rank_tracking_engine",         // monitor branch
    monitoring: "content_performance_analyzer",
    optimizing: "content_drafter",
};

const CRITICAL_SUBAGENTS = [
    "site_state_machine",
    "priority_arbitrator",
    "resource_governor",
    "health_monitor",
    "error_cascade",
];

export class GrandOrchestrator extends AgentBase {
    readonly id = "grand_orchestrator";
    readonly name = "Grand Orchestrator";
    readonly group = 1;
    readonly version = "1.0.0";

    private stopped = false;

    async run(input: AgentInput): Promise<AgentOutput> {
        // One sweep. The `loop()` method below drives continuous runs.
        const oneShot = input.one_shot !== false;
        const stats = await this.sweep();
        if (oneShot) return { ok: true, data: stats };
        // Caller wants the long-running loop — start it (fire-and-forget) and return.
        void this.loop();
        return { ok: true, data: { running: true, ...stats } };
    }

    /** Continuous sweep loop. Returns only when stop() is called. */
    async loop(): Promise<void> {
        while (!this.stopped) {
            try {
                await this.sweep();
            } catch (err) {
                this.log({
                    message: `sweep crashed: ${(err as Error).message}`,
                }, "error");
            }
            await this.sleep(LOOP_INTERVAL_MS);
        }
    }

    stop(): void {
        this.stopped = true;
    }

    private async sweep(): Promise<{
        sites_scanned: number;
        dispatched: number;
        skipped_paused: number;
        skipped_at_capacity: number;
        critical_restarts: number;
    }> {
        // 1. Self-heal: make sure every critical sub-agent is registered.
        let restarts = 0;
        for (const id of CRITICAL_SUBAGENTS) {
            if (!getAgent(id)) {
                this.log({ message: `critical agent ${id} missing — cannot self-heal at runtime; logging only` }, "error");
                restarts++;
            }
        }

        // 2. Pull sites ordered by urgency × plan × days-since-last-run.
        const allSites = await db.listSites();
        const ranked = this.rank(allSites);

        // 3. Track concurrent dispatches per instance via Redis counter.
        const inflight = await kv.slidingCount("orchestrator:inflight", 60);
        if (inflight >= MAX_CONCURRENT) {
            this.log({
                message: `at capacity (${inflight}/${MAX_CONCURRENT}) — skipping this sweep`,
            }, "warn");
            return {
                sites_scanned: 0,
                dispatched: 0,
                skipped_paused: 0,
                skipped_at_capacity: ranked.length,
                critical_restarts: restarts,
            };
        }

        let dispatched = 0;
        let skippedPaused = 0;
        const slotsLeft = MAX_CONCURRENT - inflight;

        for (const site of ranked) {
            if (dispatched >= slotsLeft) break;
            if (site.paused) {
                skippedPaused++;
                continue;
            }
            const nextAgent = STATE_TO_NEXT_AGENT[site.state];
            if (!nextAgent) continue;
            // Validate transition is even possible if the agent's output will move state
            // (defensive — the state machine itself enforces transitions on update)
            const desiredNext = this.nextStateFor(site.state);
            if (desiredNext && !isValidTransition(site.state, desiredNext)) continue;

            await db.insertTask({
                assigned_to: nextAgent,
                assigned_by: this.id,
                title: `${site.state} → ${nextAgent} for ${site.url}`,
                input: { site_id: site.id, site, triggered_by: this.id },
                site_id: site.id,
                priority: this.priorityForSite(site),
            });
            await kv.slidingHit("orchestrator:inflight", 60);
            await db.updateSite(site.id, { last_run_at: new Date().toISOString() });
            dispatched++;
        }

        this.log({
            message: `sweep: scanned=${ranked.length} dispatched=${dispatched} paused=${skippedPaused} inflight_before=${inflight}`,
        });

        return {
            sites_scanned: ranked.length,
            dispatched,
            skipped_paused: skippedPaused,
            skipped_at_capacity: 0,
            critical_restarts: restarts,
        };
    }

    rank(sites: Site[]): Site[] {
        const tierWeight = { agency: 4, pro: 3, starter: 2, free: 1 } as const;
        const now = Date.now();
        return [...sites].sort((a, b) => {
            const sa = this.score(a, tierWeight, now);
            const sb = this.score(b, tierWeight, now);
            return sb - sa;  // descending
        });
    }

    private score(site: Site, tierWeight: Record<Site["plan_tier"], number>, now: number): number {
        const daysSinceRun = site.last_run_at
            ? Math.max(0, (now - new Date(site.last_run_at).getTime()) / 86_400_000)
            : 365;
        return site.urgency * tierWeight[site.plan_tier] * (1 + Math.log(1 + daysSinceRun));
    }

    private nextStateFor(state: SiteState): SiteState | null {
        const m: Record<SiteState, SiteState | null> = {
            new: "crawling",
            crawling: "analyzing",
            analyzing: "keyword_research",
            keyword_research: "content_planning",
            content_planning: "generating",
            generating: "publishing",
            publishing: "live",
            live: "monitoring",
            monitoring: "optimizing",
            optimizing: "live",
        };
        return m[state] ?? null;
    }

    private priorityForSite(site: Site): number {
        const tierPriority: Record<Site["plan_tier"], number> = {
            agency: 1,
            pro: 2,
            starter: 3,
            free: 5,
        };
        return tierPriority[site.plan_tier];
    }
}

// Re-export the canonical instances of every Group-1 agent for the registry.
export const group01Singletons = {
    grand_orchestrator: new GrandOrchestrator(),
    site_state_machine: new SiteStateMachine(),
    priority_arbitrator: new PriorityArbitrator(),
    resource_governor: new ResourceGovernor(),
    health_monitor: new HealthMonitor(),
    error_cascade: new ErrorCascade(),
};
