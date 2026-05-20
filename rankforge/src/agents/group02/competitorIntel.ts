// 018 — Competitor Intelligence Agent.
// Compares our parsed corpus to each competitor's parsed corpus.
// Heavy DataForSEO/LLM parts are stubbed behind clean interfaces.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";

export interface CompetitorInput {
    domain: string;
    parsed_pages?: ParsedPage[];
    estimated_da?: number;            // pulled from DataForSEO if creds set
}

export interface CompetitorReport {
    domain: string;
    page_count: number;
    avg_word_count: number;
    schema_types: string[];
    estimated_da_tier: "low" | "medium" | "high" | "unknown";
    top_topics: string[];              // simple TF heuristic
    content_gaps_vs_us: string[];      // topics they have, we don't
    style_descriptors: string[];       // placeholder; LLM-driven
}

function topTopics(pages: ParsedPage[], k: number = 5): string[] {
    const freq = new Map<string, number>();
    const stop = new Set(["the", "and", "for", "with", "that", "this", "from", "have", "are", "but"]);
    for (const p of pages) {
        const tokens = p.text_excerpt.toLowerCase().match(/[a-z]{5,}/g) ?? [];
        for (const t of tokens) if (!stop.has(t)) freq.set(t, (freq.get(t) ?? 0) + 1);
    }
    return Array.from(freq.entries()).sort((a, b) => b[1] - a[1]).slice(0, k).map(([w]) => w);
}

function daTier(da?: number): CompetitorReport["estimated_da_tier"] {
    if (da === undefined) return "unknown";
    if (da >= 60) return "high";
    if (da >= 30) return "medium";
    return "low";
}

export function compareCompetitor(
    us: ParsedPage[],
    competitor: CompetitorInput,
): CompetitorReport {
    const cps = competitor.parsed_pages ?? [];
    const ourTopics = new Set(topTopics(us, 30));
    const compTopics = topTopics(cps, 30);
    const gaps = compTopics.filter(t => !ourTopics.has(t)).slice(0, 10);
    const schemaTypes = Array.from(new Set(cps.flatMap(p => p.schemas.map(s => s.type ?? "Unknown"))));
    return {
        domain: competitor.domain,
        page_count: cps.length,
        avg_word_count: cps.length ? Math.round(cps.reduce((s, p) => s + p.word_count, 0) / cps.length) : 0,
        schema_types: schemaTypes,
        estimated_da_tier: daTier(competitor.estimated_da),
        top_topics: topTopics(cps, 5),
        content_gaps_vs_us: gaps,
        style_descriptors: ["TODO: LLM-driven style analysis"],
    };
}

export class CompetitorIntel extends AgentBase {
    readonly id = "competitor_intel";
    readonly name = "Competitor Intelligence Agent";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const us = (input.our_parsed as ParsedPage[] | undefined) ?? [];
        const competitors = (input.competitors as CompetitorInput[] | undefined) ?? [];
        if (us.length === 0) return { ok: false, error: "our_parsed required" };
        const reports = competitors.slice(0, 10).map(c => compareCompetitor(us, c));
        return { ok: true, data: { reports } };
    }
}
