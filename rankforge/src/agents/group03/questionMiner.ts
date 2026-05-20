// 027 — Question Keyword Miner.
// Generates ~50 customer-question keywords across standard PAA patterns.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type QuestionFormat =
    | "how_to"
    | "what_is"
    | "why_does"
    | "when_should"
    | "can_i"
    | "is_it_safe"
    | "how_much"
    | "which_is_better"
    | "whats_the_difference";

export interface QuestionKeyword {
    keyword: string;
    seed: string;
    format: QuestionFormat;
}

const FORMAT_TEMPLATES: Record<QuestionFormat, string> = {
    how_to: "how to {s}",
    what_is: "what is {s}",
    why_does: "why does {s} matter",
    when_should: "when should you use {s}",
    can_i: "can i use {s}",
    is_it_safe: "is {s} safe",
    how_much: "how much does {s} cost",
    which_is_better: "which is better {s}",
    whats_the_difference: "what is the difference between {s} options",
};

export function generateQuestionsForSeed(seed: string): QuestionKeyword[] {
    const s = seed.toLowerCase().trim();
    if (!s) return [];
    return (Object.keys(FORMAT_TEMPLATES) as QuestionFormat[]).map(format => ({
        keyword: FORMAT_TEMPLATES[format].replace("{s}", s),
        seed,
        format,
    }));
}

export class QuestionMiner extends AgentBase {
    readonly id = "question_miner";
    readonly name = "Question Keyword Miner";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const seeds = (input.seeds as string[] | undefined)
            ?? (input.keywords as string[] | undefined)
            ?? [];
        if (!Array.isArray(seeds) || seeds.length === 0) {
            return { ok: false, error: "seeds required" };
        }
        const target = (input.target as number | undefined) ?? 50;
        const all: QuestionKeyword[] = [];
        const seen = new Set<string>();
        for (const seed of seeds) {
            for (const q of generateQuestionsForSeed(seed)) {
                const k = q.keyword.toLowerCase();
                if (seen.has(k)) continue;
                seen.add(k);
                all.push(q);
                if (all.length >= target * 2) break;
            }
            if (all.length >= target * 2) break;
        }
        const questions = all.slice(0, Math.max(target, all.length));
        const byFormat: Record<string, number> = {};
        for (const q of questions) byFormat[q.format] = (byFormat[q.format] ?? 0) + 1;
        return {
            ok: true,
            data: {
                questions,
                count: questions.length,
                by_format: byFormat,
                hit_target: questions.length >= target,
            },
        };
    }
}
