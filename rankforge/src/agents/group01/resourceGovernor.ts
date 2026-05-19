// 007 — Resource Governor.
// Enforces API budgets and rate limits. Tracked in Redis as sliding windows.

import { AgentBase } from "../../core/AgentBase.ts";
import { kv } from "../../core/redis.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type ResourceKey =
    | "openai_tokens_per_min"
    | "openai_requests_per_min"
    | "openai_cost_per_day"
    | "dataforseo_credits_per_month"
    | "bing_wmt_submissions_per_day"
    | "upstash_commands_per_second";

interface Limit { windowSeconds: number; limit: number }

// Default ceilings. Real numbers should come from billing config per site.
export const DEFAULT_LIMITS: Record<ResourceKey, Limit> = {
    openai_tokens_per_min: { windowSeconds: 60, limit: 250_000 },
    openai_requests_per_min: { windowSeconds: 60, limit: 5_000 },
    openai_cost_per_day: { windowSeconds: 86_400, limit: 50_00 }, // $50.00 in cents
    dataforseo_credits_per_month: { windowSeconds: 30 * 86_400, limit: 10_000 },
    bing_wmt_submissions_per_day: { windowSeconds: 86_400, limit: 100 },
    upstash_commands_per_second: { windowSeconds: 1, limit: 1000 },
};

export type GovernorVerdict = "ok" | "slow_down" | "paused";

export class ResourceGovernor extends AgentBase {
    readonly id = "resource_governor";
    readonly name = "Resource Governor";
    readonly group = 1;
    readonly version = "1.0.0";

    /**
     * Record N units against a resource and return the current verdict.
     * Use units=0 to check status without consuming.
     */
    async hit(resource: ResourceKey, units: number = 1, siteId: string | null = null): Promise<{
        verdict: GovernorVerdict;
        used: number;
        limit: number;
        percent: number;
    }> {
        const cfg = DEFAULT_LIMITS[resource];
        const bucket = siteId ? `${resource}:${siteId}` : resource;
        let used = 0;
        for (let i = 0; i < units; i++) {
            used = await kv.slidingHit(bucket, cfg.windowSeconds);
        }
        if (units === 0) {
            used = await kv.slidingCount(bucket, cfg.windowSeconds);
        }
        const percent = used / cfg.limit;
        let verdict: GovernorVerdict = "ok";
        if (percent >= 1) verdict = "paused";
        else if (percent >= 0.8) verdict = "slow_down";
        return { verdict, used, limit: cfg.limit, percent };
    }

    async run(input: AgentInput): Promise<AgentOutput> {
        const resource = input.resource as ResourceKey | undefined;
        const units = (input.units as number | undefined) ?? 0;
        const siteId = (input.site_id as string | undefined) ?? null;

        if (resource) {
            const r = await this.hit(resource, units, siteId);
            return { ok: true, data: r };
        }

        // No specific resource → full snapshot of every limit
        const snapshot: Record<string, unknown> = {};
        for (const r of Object.keys(DEFAULT_LIMITS) as ResourceKey[]) {
            snapshot[r] = await this.hit(r, 0, siteId);
        }
        return { ok: true, data: { snapshot } };
    }
}
