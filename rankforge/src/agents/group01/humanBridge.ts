// 009 — Human Bridge.
// The only agent that talks directly to users. Approvals, alerts, digests.
// Batches non-urgent items so we never send >3 emails/day per user.

import { AgentBase } from "../../core/AgentBase.ts";
import { kv } from "../../core/redis.ts";
import { randomUUID } from "node:crypto";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type HumanIntent = "approval" | "alert" | "digest" | "onboarding" | "billing";

interface PendingApproval {
    token: string;
    user_id: string;
    action: string;
    detail: string;
    site_id: string | null;
    created_at: string;
}

const DAILY_EMAIL_CAP = 3;

export class HumanBridge extends AgentBase {
    readonly id = "human_bridge";
    readonly name = "Human Bridge";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const intent = input.intent as HumanIntent | undefined;
        const userId = (input.user_id as string | undefined) ?? "default";
        const message = (input.message as string | undefined) ?? "";

        if (!intent) return { ok: false, error: "intent required" };

        const sentToday = (await kv.slidingCount(`human_bridge:emails:${userId}`, 86_400));
        const isUrgent = intent === "alert" || intent === "approval" || intent === "billing";

        if (!isUrgent && sentToday >= DAILY_EMAIL_CAP) {
            // Defer non-urgent items into the next digest
            const queue = (await kv.get<unknown[]>(`human_bridge:digest_queue:${userId}`)) ?? [];
            queue.push({ intent, message, ts: new Date().toISOString() });
            await kv.set(`human_bridge:digest_queue:${userId}`, queue, 86_400);
            this.log({
                message: `deferred ${intent} for ${userId} (already sent ${sentToday}/${DAILY_EMAIL_CAP} today)`,
            });
            return { ok: true, data: { delivered: false, deferred: true } };
        }

        // Approval requests: mint a token, persist, return URL — the actual
        // email send is a TODO (needs SMTP creds).
        if (intent === "approval") {
            const action = (input.action as string | undefined) ?? message;
            const approval: PendingApproval = {
                token: randomUUID(),
                user_id: userId,
                action,
                detail: (input.detail as string | undefined) ?? "",
                site_id: (input.site_id as string | undefined) ?? null,
                created_at: new Date().toISOString(),
            };
            await kv.set(`human_bridge:approval:${approval.token}`, approval, 7 * 86_400);
            await this.deliverEmail(userId, `Approval needed: ${action}`, [
                approval.detail,
                "",
                `Approve: https://example.com/approve/${approval.token}`,
                `Reject:  https://example.com/reject/${approval.token}`,
            ].join("\n"));
            return { ok: true, data: { delivered: true, token: approval.token } };
        }

        // Other intents: just deliver the message
        await this.deliverEmail(userId, intent.toUpperCase(), message);
        return { ok: true, data: { delivered: true, intent } };
    }

    async resolveApproval(token: string, decision: "approved" | "rejected"): Promise<PendingApproval | null> {
        const pending = await kv.get<PendingApproval>(`human_bridge:approval:${token}`);
        if (!pending) return null;
        await kv.del(`human_bridge:approval:${token}`);
        await this.emit("approval_resolved", { decision, ...pending });
        return pending;
    }

    private async deliverEmail(userId: string, subject: string, body: string): Promise<void> {
        // TODO: real SMTP / Postmark / Resend integration when creds are set.
        await kv.slidingHit(`human_bridge:emails:${userId}`, 86_400);
        // For now, mirror to console + log table so we have a trail.
        this.log({
            message: `→ ${userId}: ${subject}`,
            data: { body: body.slice(0, 200) },
        });
    }
}
