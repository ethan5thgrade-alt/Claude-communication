// 024 — Seed Keyword Extractor.
// TF-IDF + declared-keyword extraction from page titles, H1s, meta.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface SeedExtractorPage {
    url?: string;
    title?: string;
    h1?: string | string[];
    meta_description?: string;
    text_excerpt?: string;
}

export interface SeedKeyword {
    keyword: string;
    score: number;
    source: "declared" | "implicit";
    document_frequency: number;
}

const STOPWORDS = new Set([
    "the", "and", "for", "with", "that", "this", "from", "have", "are", "but",
    "you", "your", "not", "all", "they", "their", "what", "when", "which",
    "would", "could", "should", "about", "into", "more", "than", "then",
    "some", "any", "will", "been", "were", "was", "our", "out", "use", "how",
    "can", "has", "had", "its", "who", "why", "one", "two", "get", "new",
]);

function tokenizeNgrams(text: string, maxN: number = 3): string[] {
    const words = (text.toLowerCase().match(/[a-z][a-z0-9-]{2,}/g) ?? [])
        .filter(w => !STOPWORDS.has(w));
    const out: string[] = [];
    for (let n = 1; n <= maxN; n++) {
        for (let i = 0; i + n <= words.length; i++) {
            const gram = words.slice(i, i + n).join(" ");
            if (gram.length >= 4) out.push(gram);
        }
    }
    return out;
}

export function tfIdfSeeds(pages: SeedExtractorPage[], limit: number = 30): SeedKeyword[] {
    if (pages.length === 0) return [];
    const docFreq = new Map<string, number>();
    const docTokens: Map<string, number>[] = [];
    for (const p of pages) {
        const corpus = [p.title ?? "", Array.isArray(p.h1) ? p.h1.join(" ") : (p.h1 ?? ""), p.meta_description ?? "", p.text_excerpt ?? ""].join(" ");
        const tokens = tokenizeNgrams(corpus, 3);
        const tf = new Map<string, number>();
        for (const t of tokens) tf.set(t, (tf.get(t) ?? 0) + 1);
        docTokens.push(tf);
        for (const k of tf.keys()) docFreq.set(k, (docFreq.get(k) ?? 0) + 1);
    }
    const scored = new Map<string, number>();
    const N = pages.length;
    for (const tf of docTokens) {
        for (const [term, count] of tf.entries()) {
            const df = docFreq.get(term) ?? 1;
            const idf = Math.log(1 + N / df);
            scored.set(term, (scored.get(term) ?? 0) + count * idf);
        }
    }
    const declared = new Set<string>();
    for (const p of pages) {
        for (const s of [p.title, Array.isArray(p.h1) ? p.h1.join(" ") : p.h1].filter(Boolean) as string[]) {
            for (const t of tokenizeNgrams(s, 3)) declared.add(t);
        }
    }
    const ranked = Array.from(scored.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, limit * 2);
    const seeds: SeedKeyword[] = ranked.map(([keyword, score]) => ({
        keyword,
        score: Math.round(score * 1000) / 1000,
        source: declared.has(keyword) ? "declared" : "implicit",
        document_frequency: docFreq.get(keyword) ?? 0,
    }));
    return seeds.slice(0, limit);
}

export class SeedExtractor extends AgentBase {
    readonly id = "seed_extractor";
    readonly name = "Seed Keyword Extractor";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const pages = (input.pages as SeedExtractorPage[] | undefined) ?? [];
        if (pages.length === 0) return { ok: false, error: "pages required" };
        const limit = (input.limit as number | undefined) ?? 30;
        const seeds = tfIdfSeeds(pages, limit);
        return { ok: true, data: { seeds, count: seeds.length } };
    }
}
