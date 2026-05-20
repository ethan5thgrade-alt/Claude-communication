// 025 — AI Keyword Expander.
// AI agent. Takes seeds, generates 50-100 expanded keywords (synonyms, broader,
// narrower, related, industry-specific). Accepts optional ai_fn override; the
// default stub returns deterministic synthetic expansions.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type ExpansionType = "synonym" | "broader" | "narrower" | "related" | "industry";

export interface ExpandedKeyword {
    keyword: string;
    seed: string;
    type: ExpansionType;
}

export type ExpanderFn = (
    seeds: string[],
    context: { niche?: string; audience?: string },
) => Promise<ExpandedKeyword[]>;

const SYNONYM_PREFIXES = ["top", "best", "premium", "professional"];
const BROADER_SUFFIXES = ["services", "solutions", "industry", "category"];
const NARROWER_MODIFIERS = ["for beginners", "for small business", "step by step", "in 2026"];
const RELATED_CONNECTORS = ["vs alternatives", "with examples", "explained", "guide"];
const INDUSTRY_TAGS = ["b2b", "saas", "enterprise", "diy"];

export const defaultExpander: ExpanderFn = async (seeds, ctx) => {
    const out: ExpandedKeyword[] = [];
    const niche = ctx.niche?.toLowerCase();
    for (const seed of seeds) {
        const s = seed.toLowerCase().trim();
        if (!s) continue;
        for (const p of SYNONYM_PREFIXES) out.push({ keyword: `${p} ${s}`, seed, type: "synonym" });
        for (const suf of BROADER_SUFFIXES) out.push({ keyword: `${s} ${suf}`, seed, type: "broader" });
        for (const m of NARROWER_MODIFIERS) out.push({ keyword: `${s} ${m}`, seed, type: "narrower" });
        for (const c of RELATED_CONNECTORS) out.push({ keyword: `${s} ${c}`, seed, type: "related" });
        for (const tag of INDUSTRY_TAGS) {
            if (niche && tag === niche) continue;
            out.push({ keyword: `${tag} ${s}`, seed, type: "industry" });
        }
    }
    return out;
};

function dedupeKeywords(items: ExpandedKeyword[]): ExpandedKeyword[] {
    const seen = new Set<string>();
    const result: ExpandedKeyword[] = [];
    for (const it of items) {
        const key = it.keyword.toLowerCase().trim();
        if (!key || seen.has(key)) continue;
        seen.add(key);
        result.push({ ...it, keyword: key });
    }
    return result;
}

export class KeywordExpander extends AgentBase {
    readonly id = "keyword_expander";
    readonly name = "AI Keyword Expander";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const seeds = (input.seeds as string[] | undefined)
            ?? (input.keywords as string[] | undefined)
            ?? [];
        if (!Array.isArray(seeds) || seeds.length === 0) {
            return { ok: false, error: "seeds required" };
        }
        const niche = typeof input.niche === "string" ? input.niche : undefined;
        const audience = typeof input.audience === "string" ? input.audience : undefined;
        const ai = (input.ai_fn as ExpanderFn | undefined) ?? defaultExpander;
        const raw = await ai(seeds, { niche, audience });
        const deduped = dedupeKeywords(raw);
        const min = 50;
        const max = 100;
        const expanded = deduped.slice(0, max);
        return {
            ok: true,
            data: {
                expanded,
                count: expanded.length,
                seeds_used: seeds.length,
                hit_floor: expanded.length >= min,
            },
        };
    }
}
