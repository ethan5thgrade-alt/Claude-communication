// 004 — Error Cascade Handler.
// Listens on the error channel and classifies + dispatches.
// Tracks error patterns across sites for ErrorPatternAgent.

import { AgentBase } from "../../core/AgentBase.ts";
import { db } from "../../core/db.ts";
import { kv } from "../../core/redis.ts";
import type { AgentInput, AgentOutput, ErrorClass } from "../../core/types.ts";

export function classifyError(err: { message?: string; status?: number; code?: string }): ErrorClass {
    const m = (err.message ?? "").toLowerCase();
    const s = err.status ?? 0;
    if (s === 401 || s === 403 || m.includes("unauthorized") || m.includes("forbidden")) return "auth";
    if (s === 429 || m.includes("rate limit") || m.includes("too many")) return "rate_limit";
    if (s >= 500 || m.includes("timeout") || m.includes("econnreset") || m.includes("etimedout")) return "transient";
    if (s === 400 || s === 422 || m.includes("invalid") || m.includes("validation")) return "data";
    if (s === 404) return "permanent";
    return "unknown";
}

// Retry schedule (seconds) per spec: 30s, 2m, 5m, 15m, stop
export const RETRY_DELAYS_S = [30, 120, 300, 900];

export class ErrorCascade extends AgentBase {
    readonly id = "error_cascade";
    readonly name = "Error Cascade Handler";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        // input: { failed_agent_id, attempt, error: {message, status?, code?}, site_id?, original_input? }
        const failedId = input.failed_agent_id as string | undefined;
        const attempt = (input.attempt as number | undefined) ?? 1;
        const err = (input.error as { message?: string; status?: number; code?: string } | undefined) ?? {};
        const siteId = (input.site_id as string | undefined) ?? null;
        if (!failedId) return { ok: false, error: "failed_agent_id required" };

        const cls = classifyError(err);
        // Update error-pattern counters
        await kv.slidingHit(`error:${failedId}:${cls}`, 3600);
        await kv.slidingHit(`error:${failedId}:any`, 3600);

        const action = this.decide(cls, attempt);
        await db.insertMessage({
            from_agent: this.id,
            to_agent: failedId,
            site_id: siteId,
            message_type: "error",
            payload: { class: cls, attempt, action, error: err },
            priority: cls === "auth" ? 1 : 5,
        });

        this.log({
            message: `${failedId} error[${cls}] attempt=${attempt} → ${action.kind}${action.kind === "retry" ? ` in ${action.delay_s}s` : ""}`,
            site_id: siteId,
        }, cls === "auth" ? "error" : "warn");

        if (action.kind === "alert") {
            await this.notify(
                `Agent ${failedId} hit an ${cls} error: ${err.message ?? "unknown"}. Pipeline paused for site ${siteId ?? "(none)"}.`,
                "critical",
            );
        }

        return { ok: true, data: { class: cls, action }, artifacts: action };
    }

    private decide(cls: ErrorClass, attempt: number): {
        kind: "retry" | "queue_for_window" | "alert" | "isolate" | "give_up";
        delay_s?: number;
    } {
        switch (cls) {
            case "transient":
                if (attempt - 1 < RETRY_DELAYS_S.length) {
                    return { kind: "retry", delay_s: RETRY_DELAYS_S[attempt - 1] };
                }
                return { kind: "give_up" };
            case "rate_limit":
                return { kind: "queue_for_window", delay_s: 60 };  // resource_governor knows the real window
            case "auth":
                return { kind: "alert" };
            case "data":
                return { kind: "retry", delay_s: 5 };  // try alternate source per spec
            case "unknown":
                return attempt === 1 ? { kind: "retry", delay_s: 30 } : { kind: "isolate" };
            case "permanent":
                return { kind: "give_up" };
        }
    }
}
