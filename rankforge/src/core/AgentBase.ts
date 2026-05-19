// AgentBase — every one of the 300 RankForge agents extends this.
//
// Inherited behaviors per the spec (Part 1, INFRASTRUCTURE):
//   - execute(): wraps run() with timing, logging, error handling, retry
//   - retry(): exponential backoff
//   - cache(): KV-backed cache check before running (TODO: not yet wired)
//   - log(): structured logging (stdout + DB + mesh)
//   - emit(): pub/sub event to AgentBus (via mesh)
//   - store(): persist result to agent_runs table
//   - notify(): forward to HumanBridge (agent 009) for human-facing alerts

import { randomUUID } from "node:crypto";
import { db } from "./db.ts";
import { getMesh } from "./meshBridge.ts";
import type {
    AgentInput, AgentOutput, AgentTrigger, LogEvent, RunStatus,
} from "./types.ts";

export abstract class AgentBase {
    abstract id: string;
    abstract name: string;
    abstract group: number;
    abstract version: string;

    abstract run(input: AgentInput): Promise<AgentOutput>;
    /** Agents this run should dispatch next. Default: none. */
    nextAgents(_output: AgentOutput): AgentTrigger[] {
        return [];
    }
    /** Pre-flight check. Default: always runs. */
    async canRun(_input: AgentInput): Promise<boolean> {
        return true;
    }

    /**
     * Wraps run() with the inherited lifecycle: timing, retry on transient
     * errors, persistence to agent_runs, and emission of next-agent triggers.
     */
    async execute(input: AgentInput, opts: { maxAttempts?: number } = {}): Promise<AgentOutput> {
        const maxAttempts = opts.maxAttempts ?? 1;
        const runId = randomUUID();
        const startedAt = Date.now();

        await db.insertRun({
            id: runId,
            agent_id: this.id,
            agent_version: this.version,
            site_id: typeof input.site_id === "string" ? input.site_id : null,
            status: "running",
            attempt: 1,
            input,
            triggered_by: typeof input.triggered_by === "string" ? input.triggered_by : "system",
        });

        if (!(await this.canRun(input))) {
            const out: AgentOutput = { ok: false, error: "canRun returned false" };
            await this.finish(runId, "skipped", out, Date.now() - startedAt);
            return out;
        }

        let lastError: Error | null = null;
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                const out = await this.run(input);
                await this.finish(runId, out.ok ? "success" : "failed", out, Date.now() - startedAt);
                if (out.ok) {
                    // Fire-and-forget the downstream triggers; orchestrator picks them up
                    const triggers = this.nextAgents(out);
                    for (const t of triggers) {
                        await db.insertTask({
                            assigned_to: t.agent_id,
                            assigned_by: this.id,
                            title: `${this.id} → ${t.agent_id}`,
                            input: t.input,
                            priority: t.priority ?? 5,
                            site_id: typeof t.input.site_id === "string" ? t.input.site_id : null,
                        });
                    }
                }
                return out;
            } catch (err) {
                lastError = err instanceof Error ? err : new Error(String(err));
                if (attempt < maxAttempts) {
                    await this.sleep(this.backoffMs(attempt));
                }
            }
        }

        const out: AgentOutput = { ok: false, error: lastError?.message ?? "unknown error" };
        await this.finish(runId, "failed", out, Date.now() - startedAt);
        return out;
    }

    private async finish(runId: string, status: RunStatus, out: AgentOutput, durationMs: number): Promise<void> {
        await db.updateRun(runId, {
            status,
            output: out,
            duration_ms: durationMs,
            completed_at: new Date().toISOString(),
            error: out.error ?? null,
        });
    }

    protected backoffMs(attempt: number): number {
        // 1s, 2s, 4s, 8s ... cap 30s
        return Math.min(1000 * 2 ** (attempt - 1), 30_000);
    }

    protected sleep(ms: number): Promise<void> {
        return new Promise(r => setTimeout(r, ms));
    }

    log(event: Partial<LogEvent> & Pick<LogEvent, "message">, level: LogEvent["level"] = "info"): void {
        const full: LogEvent = {
            level,
            agent_id: this.id,
            site_id: event.site_id ?? null,
            message: event.message,
            data: event.data,
            ts: new Date().toISOString(),
        };
        // Format: [ts] [level] [agent] message
        // eslint-disable-next-line no-console
        console.log(`[${full.ts}] [${level}] [${this.id}] ${full.message}`);
        // best-effort echo to mesh
        try { getMesh().log(`${this.id}: ${full.message}`, level); } catch { /* ignore */ }
    }

    async emit(event: string, payload: unknown): Promise<void> {
        await db.insertMessage({
            from_agent: this.id,
            to_agent: "broadcast",
            message_type: "status",
            payload: { event, data: payload },
        });
    }

    async notify(message: string, severity: "info" | "warn" | "critical" = "info"): Promise<void> {
        // Route human-facing notifications via HumanBridge (agent 009)
        await db.insertMessage({
            from_agent: this.id,
            to_agent: "human_bridge",
            message_type: "task",
            priority: severity === "critical" ? 1 : severity === "warn" ? 3 : 5,
            payload: { message, severity },
        });
    }
}
