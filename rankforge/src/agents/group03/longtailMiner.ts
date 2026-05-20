// 026 — Long-Tail Mining Agent.
// For each seed: 5 long-tail + 3 question + 2 comparison + 2 local (if location).

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type LongTailType = "longtail" | "question" | "comparison" | "local";

export interface LongTailKeyword {
    keyword: string;
    seed: string;
    type: LongTailType;
    word_count: number;
}

const LONGTAIL_TEMPLATES = [
    "best {s} for small business",
    "affordable {s} services",
    "how to choose {s}",
    "{s} tips and tricks",
    "{s} buying guide",
];

const QUESTION_TEMPLATES = [
    "what is the best {s}",
    "how does {s} work",
    "why is {s} important",
];

const COMPARISON_TEMPLATES = [
    "{s} vs alternatives",
    "{s} comparison guide",
];

const LOCAL_TEMPLATES = [
    "{s} in {loc}",
    "{s} near {loc}",
];

function fill(template: string, seed: string, loc?: string): string {
    return template.replace("{s}", seed).replace("{loc}", loc ?? "").trim();
}

function wordCount(s: string): number {
    return s.split(/\s+/).filter(Boolean).length;
}

export function mineLongTails(
    seed: string,
    location?: string,
): LongTailKeyword[] {
    const s = seed.toLowerCase().trim();
    if (!s) return [];
    const out: LongTailKeyword[] = [];
    for (const t of LONGTAIL_TEMPLATES) {
        const k = fill(t, s);
        out.push({ keyword: k, seed, type: "longtail", word_count: wordCount(k) });
    }
    for (const t of QUESTION_TEMPLATES) {
        const k = fill(t, s);
        out.push({ keyword: k, seed, type: "question", word_count: wordCount(k) });
    }
    for (const t of COMPARISON_TEMPLATES) {
        const k = fill(t, s);
        out.push({ keyword: k, seed, type: "comparison", word_count: wordCount(k) });
    }
    if (location && location.trim()) {
        for (const t of LOCAL_TEMPLATES) {
            const k = fill(t, s, location.trim());
            out.push({ keyword: k, seed, type: "local", word_count: wordCount(k) });
        }
    }
    return out;
}

export class LongTailMiner extends AgentBase {
    readonly id = "longtail_miner";
    readonly name = "Long-Tail Mining Agent";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const seeds = (input.seeds as string[] | undefined)
            ?? (input.keywords as string[] | undefined)
            ?? [];
        if (!Array.isArray(seeds) || seeds.length === 0) {
            return { ok: false, error: "seeds required" };
        }
        const location = typeof input.location === "string" ? input.location : undefined;
        const all: LongTailKeyword[] = [];
        const seen = new Set<string>();
        for (const seed of seeds) {
            for (const k of mineLongTails(seed, location)) {
                const key = k.keyword.toLowerCase();
                if (seen.has(key)) continue;
                seen.add(key);
                all.push(k);
            }
        }
        const byType: Record<LongTailType, number> = { longtail: 0, question: 0, comparison: 0, local: 0 };
        for (const k of all) byType[k.type]++;
        return { ok: true, data: { longtails: all, count: all.length, by_type: byType } };
    }
}
