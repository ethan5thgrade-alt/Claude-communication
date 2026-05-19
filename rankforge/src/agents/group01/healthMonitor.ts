// 008 — Agent Health Monitor.
// Computes success rate / avg / p95 from agent_runs. Marks degraded agents.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput, AgentRun } from "../../core/types.ts";

export interface AgentHealth {
    agent_id: string;
    sample_size: number;
    success_rate: number;          // 0.0 - 1.0
    avg_duration_ms: number;
    p95_duration_ms: number;
    error_breakdown: Record<string, number>;
    status: "green" | "yellow" | "red";
}

export function summarize(runs: AgentRun[]): AgentHealth {
    if (runs.length === 0) {
        return {
            agent_id: "unknown",
            sample_size: 0,
            success_rate: 1,
            avg_duration_ms: 0,
            p95_duration_ms: 0,
            error_breakdown: {},
            status: "green",
        };
    }
    const agentId = runs[0].agent_id;
    const successCount = runs.filter(r => r.status === "success").length;
    const successRate = successCount / runs.length;
    const durations = runs
        .map(r => r.duration_ms ?? 0)
        .filter(d => d > 0)
        .sort((a, b) => a - b);
    const avg = durations.length
        ? durations.reduce((a, b) => a + b, 0) / durations.length
        : 0;
    const p95 = durations.length
        ? durations[Math.min(durations.length - 1, Math.floor(durations.length * 0.95))]
        : 0;
    const breakdown: Record<string, number> = {};
    for (const r of runs) {
        if (r.status === "failed" && r.error) {
            const key = r.error.slice(0, 60);
            breakdown[key] = (breakdown[key] ?? 0) + 1;
        }
    }
    const failureRate = 1 - successRate;
    const status: "green" | "yellow" | "red" =
        failureRate > 0.2 ? "red" : failureRate > 0.05 ? "yellow" : "green";

    return {
        agent_id: agentId,
        sample_size: runs.length,
        success_rate: successRate,
        avg_duration_ms: avg,
        p95_duration_ms: p95,
        error_breakdown: breakdown,
        status,
    };
}

export class HealthMonitor extends AgentBase {
    readonly id = "health_monitor";
    readonly name = "Agent Health Monitor";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        // For unit tests, the caller passes in a `runs` array directly so the
        // test isn't coupled to db internals. In production this would query
        // db.listRuns({agent_id, since: 1h ago}) — wire up when the
        // real DB adapter lands.
        const runs = (input.runs as AgentRun[] | undefined) ?? [];
        const byAgent = new Map<string, AgentRun[]>();
        for (const r of runs) {
            const list = byAgent.get(r.agent_id) ?? [];
            list.push(r);
            byAgent.set(r.agent_id, list);
        }
        const reports: AgentHealth[] = [];
        for (const [agent_id, list] of byAgent.entries()) {
            const h = summarize(list);
            reports.push({ ...h, agent_id });
            if (h.status === "red") {
                await this.notify(
                    `Agent ${agent_id} is RED: ${(h.success_rate * 100).toFixed(1)}% success over ${h.sample_size} runs`,
                    "warn",
                );
            }
        }
        return { ok: true, data: { reports } };
    }
}
