// 037 — People Also Ask Miner.
// For each primary keyword, generates likely PAA questions (heuristic templates).

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface PaaResult {
    keyword: string;
    questions: string[];
}

const TEMPLATES: ((kw: string) => string)[] = [
    kw => `What is ${kw}?`,
    kw => `How does ${kw} work?`,
    kw => `Why is ${kw} important?`,
    kw => `How much does ${kw} cost?`,
    kw => `Is ${kw} worth it?`,
    kw => `What are the benefits of ${kw}?`,
    kw => `How to choose ${kw}?`,
    kw => `What is the best ${kw}?`,
    kw => `How long does ${kw} last?`,
    kw => `Can you ${kw} at home?`,
];

function clean(kw: string): string {
    return kw.trim().toLowerCase().replace(/[?.!]$/, "");
}

export function minePaa(keyword: string, maxQuestions: number = 8): PaaResult {
    const kw = clean(keyword);
    const seen = new Set<string>();
    const out: string[] = [];
    for (const t of TEMPLATES) {
        const q = t(kw).replace(/\s+/g, " ").trim();
        // Cap-first letter
        const formatted = q.charAt(0).toUpperCase() + q.slice(1);
        if (!seen.has(formatted)) {
            seen.add(formatted);
            out.push(formatted);
        }
        if (out.length >= maxQuestions) break;
    }
    return { keyword, questions: out };
}

export class PaaMiner extends AgentBase {
    readonly id = "paa_miner";
    readonly name = "People Also Ask Miner";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = input.keywords as string[] | undefined;
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords array required" };
        }
        const maxPer = (input.max_per_keyword as number | undefined) ?? 8;
        const results = keywords.map(k => minePaa(k, maxPer));
        const total = results.reduce((s, r) => s + r.questions.length, 0);
        return {
            ok: true,
            data: {
                results,
                total_questions: total,
            },
        };
    }
}
