// 047 — Press Release Writer.
// Inverted-pyramid format covering Who/What/When/Where/Why + quote.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type PressTrigger = "new_product" | "new_service" | "milestone" | "community" | "seasonal";

export interface PressReleaseFiveWs {
    who: string;
    what: string;
    when: string;
    where: string;
    why: string;
}

export type LlmFn = (prompt: string) => Promise<string>;

const PR_SUBMISSION_SITES = [
    "PRWeb",
    "PR Newswire",
    "EIN Presswire",
    "Newswire.com",
    "OpenPR",
    "Local newspaper online portals",
    "Local Patch.com sub-site",
    "Chamber of Commerce news page",
];

function formatDateline(city: string, state: string, dateISO: string): string {
    const d = new Date(dateISO);
    const month = d.toLocaleString("en-US", { month: "long", timeZone: "UTC" });
    const day = d.getUTCDate();
    const year = d.getUTCFullYear();
    return `${city.toUpperCase()}, ${state.toUpperCase()} — ${month} ${day}, ${year}`;
}

function stubBody(business: string, headline: string, fiveWs: PressReleaseFiveWs, quote: string): string {
    return [
        `${fiveWs.what} ${business} announced today, marking a milestone for ${fiveWs.who}.`,
        ``,
        `${fiveWs.why} The announcement comes after months of preparation and reflects ongoing investment in the local community.`,
        ``,
        `"${quote}" said the owner of ${business}.`,
        ``,
        `${headline} ${fiveWs.when} at ${fiveWs.where}. Members of the public and local media are invited to attend.`,
        ``,
        `### About ${business}`,
        ``,
        `${business} serves the local community with a commitment to quality and personal service.`,
        ``,
        `### Media Contact`,
        ``,
        `${business} Press Office`,
        `press@example.com`,
        ``,
        `###`,
    ].join("\n");
}

export class PressReleaseWriter extends AgentBase {
    readonly id = "press_release_writer";
    readonly name = "Press Release Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const business = (input.business as string | undefined) ?? (input.client as string | undefined);
        if (!business) return { ok: false, error: "business required" };
        const trigger = ((input.trigger as PressTrigger | undefined) ?? "new_service");
        const headline = (input.headline as string | undefined)
            ?? `${business} Announces ${trigger.replace(/_/g, " ")}`;
        const city = (input.city as string | undefined) ?? "Springfield";
        const state = (input.state as string | undefined) ?? "IL";
        const dateISO = (input.release_date as string | undefined) ?? new Date().toISOString();

        const fiveWs: PressReleaseFiveWs = {
            who: (input.who as string | undefined) ?? `${business} and its customers`,
            what: (input.what as string | undefined) ?? `A ${trigger.replace(/_/g, " ")} for the local community`,
            when: (input.when as string | undefined) ?? new Date(dateISO).toDateString(),
            where: (input.where as string | undefined) ?? `${city}, ${state}`,
            why: (input.why as string | undefined) ?? `To better serve local customers and expand options in ${city}.`,
        };
        const quote = (input.quote as string | undefined)
            ?? `We're excited to bring this to ${city}. Our customers asked for it and we're proud to deliver.`;

        const llmFn = input.llm_fn as LlmFn | undefined;
        let body: string;
        if (llmFn) {
            body = await llmFn(`Headline: ${headline}\nBusiness: ${business}\nWrite an inverted-pyramid press release body.`);
            if (!body || body.length < 50) body = stubBody(business, headline, fiveWs, quote);
        } else {
            body = stubBody(business, headline, fiveWs, quote);
        }

        const dateline = formatDateline(city, state, dateISO);
        const fullText = `FOR IMMEDIATE RELEASE\n\n${headline}\n\n${dateline} — ${body}`;

        return {
            ok: true,
            data: {
                headline,
                dateline,
                trigger,
                business,
                city,
                state,
                five_ws: fiveWs,
                quote,
                body,
                full_text: fullText,
                distribution_list: PR_SUBMISSION_SITES,
            },
        };
    }
}
