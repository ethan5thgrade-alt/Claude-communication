// 005 — Priority Arbitrator.
// Allocates global job slots by plan tier with starvation prevention.
// Spec: agency 40% / pro 30% / starter 20% / free 10%. Within tier:
// manual > scheduled > cron. Free tier always gets >=1 slot.

import { AgentBase } from "../../core/AgentBase.ts";
import { db } from "../../core/db.ts";
import type { AgentInput, AgentOutput, AgentTask, PlanTier } from "../../core/types.ts";

const TIER_WEIGHTS: Record<PlanTier, number> = {
    agency: 0.4,
    pro: 0.3,
    starter: 0.2,
    free: 0.1,
};

const TRIGGER_PRIORITY: Record<string, number> = {
    user: 1,        // manual
    scheduled: 2,
    cron: 3,
};

export interface AllocationPlan {
    capacity: number;
    perTier: Record<PlanTier, number>;
}

export function allocateSlots(capacity: number, demand: Record<PlanTier, number>): AllocationPlan {
    const perTier: Record<PlanTier, number> = { agency: 0, pro: 0, starter: 0, free: 0 };
    if (capacity <= 0) return { capacity, perTier };

    // Initial weighted allocation
    for (const tier of Object.keys(TIER_WEIGHTS) as PlanTier[]) {
        perTier[tier] = Math.floor(capacity * TIER_WEIGHTS[tier]);
    }

    // Starvation prevention: free tier always gets >=1 if there's demand
    if (demand.free > 0 && perTier.free === 0) {
        perTier.free = 1;
    }

    // Cap each tier by actual demand and redistribute slack
    let slack = capacity;
    for (const tier of Object.keys(TIER_WEIGHTS) as PlanTier[]) {
        perTier[tier] = Math.min(perTier[tier], demand[tier]);
        slack -= perTier[tier];
    }
    // Redistribute slack in tier-priority order (agency first)
    const orderedTiers: PlanTier[] = ["agency", "pro", "starter", "free"];
    while (slack > 0) {
        let progressed = false;
        for (const tier of orderedTiers) {
            if (perTier[tier] < demand[tier]) {
                perTier[tier] += 1;
                slack -= 1;
                progressed = true;
                if (slack === 0) break;
            }
        }
        if (!progressed) break;
    }
    return { capacity, perTier };
}

export class PriorityArbitrator extends AgentBase {
    readonly id = "priority_arbitrator";
    readonly name = "Priority Arbitrator";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const capacity = (input.capacity as number | undefined) ?? 50;
        const sites = await db.listSites({ paused: false });
        const tierToSites = new Map<PlanTier, string[]>();
        for (const s of sites) {
            const list = tierToSites.get(s.plan_tier) ?? [];
            list.push(s.id);
            tierToSites.set(s.plan_tier, list);
        }
        const allTasks = await db.listTasks({ status: "pending" });

        const demand: Record<PlanTier, number> = { agency: 0, pro: 0, starter: 0, free: 0 };
        const byTier: Record<PlanTier, AgentTask[]> = {
            agency: [], pro: [], starter: [], free: [],
        };
        for (const t of allTasks) {
            // Lookup tier via site
            const tier = sites.find(s => s.id === t.site_id)?.plan_tier ?? "free";
            byTier[tier].push(t);
            demand[tier] += 1;
        }

        const plan = allocateSlots(capacity, demand);

        // Pick the highest-priority N tasks per tier
        const chosen: AgentTask[] = [];
        for (const tier of Object.keys(byTier) as PlanTier[]) {
            const tasks = byTier[tier];
            tasks.sort((a, b) => {
                // sort by trigger source, then explicit priority
                const aw = TRIGGER_PRIORITY[a.assigned_by] ?? 5;
                const bw = TRIGGER_PRIORITY[b.assigned_by] ?? 5;
                if (aw !== bw) return aw - bw;
                return a.priority - b.priority;
            });
            chosen.push(...tasks.slice(0, plan.perTier[tier]));
        }

        this.log({
            message: `capacity=${capacity} demand=${JSON.stringify(demand)} allocated=${JSON.stringify(plan.perTier)} chose=${chosen.length}`,
        });
        return { ok: true, data: { plan, chosen_tasks: chosen.map(t => t.id) } };
    }
}
