// 002 — Site State Machine.
// Enforces valid transitions. Stores current state + history in Redis (KV).
// Emits state_change events to all subscribed agents (via AgentBus / mesh).

import { AgentBase } from "../../core/AgentBase.ts";
import { db } from "../../core/db.ts";
import { kv } from "../../core/redis.ts";
import type { AgentInput, AgentOutput, SiteState } from "../../core/types.ts";

const VALID: Record<SiteState, SiteState[]> = {
    new: ["crawling"],
    crawling: ["analyzing"],
    analyzing: ["keyword_research"],
    keyword_research: ["content_planning"],
    content_planning: ["generating"],
    generating: ["publishing"],
    publishing: ["live"],
    live: ["monitoring", "generating"],   // re-enter the loop for new content
    monitoring: ["optimizing", "live"],
    optimizing: ["live"],
};

export function isValidTransition(from: SiteState, to: SiteState): boolean {
    return (VALID[from] ?? []).includes(to);
}

export class SiteStateMachine extends AgentBase {
    readonly id = "site_state_machine";
    readonly name = "Site State Machine";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        // input: { site_id, to: SiteState, reason?: string }
        const siteId = input.site_id as string | undefined;
        const to = input.to as SiteState | undefined;
        const reason = (input.reason as string | undefined) ?? "";
        if (!siteId || !to) {
            return { ok: false, error: "site_id and to are required" };
        }
        const site = await db.getSite(siteId);
        if (!site) return { ok: false, error: `site ${siteId} not found` };

        if (!isValidTransition(site.state, to)) {
            this.log({
                message: `INVALID TRANSITION ${site.state} → ${to} for site ${siteId}`,
                site_id: siteId,
            }, "warn");
            // alert GrandOrchestrator per spec
            await this.emit("state_transition_rejected", { site_id: siteId, from: site.state, to, reason });
            return { ok: false, error: `invalid transition ${site.state} → ${to}` };
        }

        const fromState = site.state;
        await db.updateSite(siteId, {
            state: to,
            state_updated_at: new Date().toISOString(),
        });
        await db.recordTransition(siteId, fromState, to, reason);
        await kv.set(`site:${siteId}:state`, to);
        await this.emit("state_change", { site_id: siteId, from: fromState, to, reason });
        return { ok: true, data: { site_id: siteId, from: fromState, to } };
    }
}
