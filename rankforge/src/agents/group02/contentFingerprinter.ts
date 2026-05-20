// 020 — Content Fingerprinter.
// AI agent that reads all page content + outputs niche fingerprint. Real
// version calls an LLM; this stub returns deterministic heuristics so the
// pipeline still produces structured output without an API key.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";

export interface SiteFingerprint {
    primary_niche: string;
    sub_niches: string[];
    topics_covered: string[];
    content_gaps: string[];
    tone_descriptors: string[];
    target_persona: string;
    geographic_focus: string;
    topical_authority: Record<string, number>;  // 0-10 per cluster
    maturity_level: "beginner" | "intermediate" | "expert";
    brand_voice: string;
    source: "heuristic" | "llm";
}

function tokenize(pages: ParsedPage[]): Map<string, number> {
    const stop = new Set([
        "the", "and", "for", "with", "that", "this", "from", "have", "are", "but",
        "you", "your", "not", "all", "they", "their", "what", "when", "which", "would",
        "could", "should", "about", "into", "more", "than", "then", "some", "any",
    ]);
    const freq = new Map<string, number>();
    for (const p of pages) {
        const tokens = p.text_excerpt.toLowerCase().match(/[a-z]{4,}/g) ?? [];
        for (const t of tokens) if (!stop.has(t)) freq.set(t, (freq.get(t) ?? 0) + 1);
    }
    return freq;
}

export function heuristicFingerprint(pages: ParsedPage[]): SiteFingerprint {
    const freq = tokenize(pages);
    const sorted = Array.from(freq.entries()).sort((a, b) => b[1] - a[1]);
    const top = sorted.slice(0, 30).map(([w]) => w);
    const avgWords = pages.length ? pages.reduce((s, p) => s + p.word_count, 0) / pages.length : 0;
    const avgReadingLevel = pages.length ? pages.reduce((s, p) => s + p.reading_level, 0) / pages.length : 0;
    const maturity: SiteFingerprint["maturity_level"] =
        avgReadingLevel > 13 ? "expert" : avgReadingLevel > 10 ? "intermediate" : "beginner";
    return {
        primary_niche: top[0] ?? "unknown",
        sub_niches: top.slice(1, 6),
        topics_covered: top.slice(0, 15),
        content_gaps: [],   // requires LLM
        tone_descriptors: avgWords > 1500 ? ["in-depth", "informative"] : ["concise", "actionable"],
        target_persona: maturity === "expert" ? "experienced practitioner" : maturity === "intermediate" ? "growing user" : "newcomer",
        geographic_focus: "unknown",   // requires LLM/geo signals
        topical_authority: Object.fromEntries(top.slice(0, 5).map(t => [t, Math.min(10, Math.round((freq.get(t) ?? 0) / 5))])),
        maturity_level: maturity,
        brand_voice: maturity === "expert" ? "authoritative, technical" : maturity === "intermediate" ? "knowledgeable, friendly" : "encouraging, simple",
        source: "heuristic",
    };
}

export class ContentFingerprinter extends AgentBase {
    readonly id = "content_fingerprinter";
    readonly name = "Content Fingerprinter";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const parsed = (input.parsed as ParsedPage[] | undefined) ?? [];
        if (parsed.length === 0) return { ok: false, error: "no parsed pages" };
        // TODO: if OPENAI_API_KEY set, call LLM for richer fingerprint
        const fp = heuristicFingerprint(parsed);
        return { ok: true, data: fp };
    }
}
