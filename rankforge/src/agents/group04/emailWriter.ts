// 048 — Email Sequence Writer.
// Builds a 5-7 email lead-nurture sequence; each email has 3 subject variants,
// preview text, and body. Connects blog content to email CTAs.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type CampaignType = "welcome" | "nurture" | "promotional";

export interface EmailMessage {
    sequence_number: number;
    purpose: string;
    subject_variants: [string, string, string];
    preview_text: string;
    body: string;
    cta: { text: string; url: string };
    linked_blog: string | null;
}

export type LlmFn = (prompt: string) => Promise<string>;

const PURPOSE_BY_INDEX_WELCOME = [
    "Welcome and set expectations",
    "Share the founder story",
    "Deliver a quick-win tip",
    "Introduce best-selling offer",
    "Social proof and testimonials",
    "Time-limited bonus",
    "Re-engagement check-in",
];

const PURPOSE_BY_INDEX_NURTURE = [
    "Educational deep-dive",
    "Case study spotlight",
    "Common-mistake breakdown",
    "Tool / process walkthrough",
    "Frequently asked questions",
    "Customer transformation story",
    "Soft CTA recap",
];

const PURPOSE_BY_INDEX_PROMOTIONAL = [
    "Announce offer",
    "Show value and savings",
    "Address objections",
    "Social proof",
    "Last-chance reminder",
    "Final hours",
    "After-sale follow-up",
];

function purposesFor(type: CampaignType): string[] {
    if (type === "welcome") return PURPOSE_BY_INDEX_WELCOME;
    if (type === "promotional") return PURPOSE_BY_INDEX_PROMOTIONAL;
    return PURPOSE_BY_INDEX_NURTURE;
}

function stubSubjects(topic: string, purpose: string): [string, string, string] {
    return [
        `${purpose} — about ${topic}`,
        `Quick read: ${topic}`,
        `${topic}: the one thing most people miss`,
    ];
}

function stubBody(topic: string, purpose: string, blog: string | null): string {
    const intro = `Hi {{first_name}},`;
    const para1 = `Today we wanted to talk about ${topic}. ${purpose} is at the heart of what we do, and we've seen it transform results when applied consistently.`;
    const para2 = blog
        ? `For a deeper dive, we wrote a full guide here: ${blog}. It walks through the steps in detail.`
        : `Hit reply if this resonates — we read every message.`;
    const sign = `Talk soon,\nThe team`;
    return [intro, "", para1, "", para2, "", sign].join("\n");
}

export class EmailWriter extends AgentBase {
    readonly id = "email_writer";
    readonly name = "Email Sequence Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const topic = (input.topic as string | undefined) ?? (input.keyword as string | undefined);
        if (!topic) return { ok: false, error: "topic required" };
        const campaignType = ((input.campaign_type as CampaignType | undefined) ?? "nurture");
        const requested = (input.sequence_length as number | undefined) ?? 6;
        const sequenceLength = Math.max(5, Math.min(7, requested));
        const blogLinks = (input.blog_urls as string[] | undefined) ?? [];
        const ctaUrl = (input.cta_url as string | undefined) ?? "https://example.com/";
        const ctaText = (input.cta_text as string | undefined) ?? "Read the full guide";
        const llmFn = input.llm_fn as LlmFn | undefined;

        const purposes = purposesFor(campaignType);
        const emails: EmailMessage[] = [];
        for (let i = 0; i < sequenceLength; i++) {
            const purpose = purposes[i] ?? `Follow-up #${i + 1}`;
            const linkedBlog = blogLinks[i] ?? null;
            let subjects: [string, string, string];
            let body: string;
            if (llmFn) {
                const raw = await llmFn(`Topic: ${topic}\nPurpose: ${purpose}\nWrite 3 subject lines then the body.`);
                const lines = raw.split("\n").filter(l => l.trim().length > 0);
                subjects = [
                    lines[0] ?? stubSubjects(topic, purpose)[0],
                    lines[1] ?? stubSubjects(topic, purpose)[1],
                    lines[2] ?? stubSubjects(topic, purpose)[2],
                ];
                body = lines.slice(3).join("\n") || stubBody(topic, purpose, linkedBlog);
            } else {
                subjects = stubSubjects(topic, purpose);
                body = stubBody(topic, purpose, linkedBlog);
            }
            const previewText = `${purpose} — a quick note about ${topic}.`.slice(0, 100);
            emails.push({
                sequence_number: i + 1,
                purpose,
                subject_variants: subjects,
                preview_text: previewText,
                body,
                cta: { text: ctaText, url: linkedBlog ?? ctaUrl },
                linked_blog: linkedBlog,
            });
        }

        return {
            ok: true,
            data: {
                topic,
                campaign_type: campaignType,
                emails,
                email_count: emails.length,
            },
        };
    }
}
