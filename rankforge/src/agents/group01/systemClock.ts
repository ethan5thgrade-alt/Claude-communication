// 010 — System Clock.
// The heartbeat. Triggers scheduled and recurring agents. Per-site timezone-aware.

import { AgentBase } from "../../core/AgentBase.ts";
import { db } from "../../core/db.ts";
import { kv } from "../../core/redis.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface ScheduledJob {
    id: string;
    agent_id: string;
    site_id: string | null;
    cron_or_at: string;          // ISO-8601 or "every:60s" or unix-cron
    input: AgentInput;
    last_fired_at: string | null;
}

/** Returns true if `job.cron_or_at` is due relative to `now`. */
export function isDue(job: ScheduledJob, now: Date = new Date()): boolean {
    if (job.cron_or_at.startsWith("every:")) {
        const intervalSec = parseInterval(job.cron_or_at.slice("every:".length));
        if (intervalSec === null) return false;
        if (!job.last_fired_at) return true;
        const lastFired = new Date(job.last_fired_at).getTime();
        return now.getTime() - lastFired >= intervalSec * 1000;
    }
    // ISO-8601 one-shot
    const ts = Date.parse(job.cron_or_at);
    if (!Number.isNaN(ts)) {
        if (job.last_fired_at) return false;  // one-shot, already fired
        return now.getTime() >= ts;
    }
    return false;
}

function parseInterval(s: string): number | null {
    const m = s.match(/^(\d+)\s*(s|m|h|d)$/);
    if (!m) return null;
    const n = Number(m[1]);
    switch (m[2]) {
        case "s": return n;
        case "m": return n * 60;
        case "h": return n * 3600;
        case "d": return n * 86_400;
    }
    return null;
}

export class SystemClock extends AgentBase {
    readonly id = "system_clock";
    readonly name = "System Clock";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const now = new Date();
        const jobs = (input.jobs as ScheduledJob[] | undefined) ?? [];
        const dispatched: string[] = [];

        for (const job of jobs) {
            if (!isDue(job, now)) continue;
            // Redis lock to prevent double-dispatch across clock instances
            const lockKey = `clock:lock:${job.id}`;
            const got = await kv.lockAcquire(lockKey, 60);
            if (!got) continue;
            try {
                await db.insertTask({
                    assigned_to: job.agent_id,
                    assigned_by: this.id,
                    title: `scheduled: ${job.agent_id}`,
                    input: job.input,
                    site_id: job.site_id ?? undefined,
                    priority: 2,
                });
                job.last_fired_at = now.toISOString();
                dispatched.push(job.id);
            } finally {
                await kv.lockRelease(lockKey);
            }
        }

        return { ok: true, data: { dispatched, count: dispatched.length } };
    }
}
