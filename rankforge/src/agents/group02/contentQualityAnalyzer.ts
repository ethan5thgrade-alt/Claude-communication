// 017 — Content Quality Analyzer.
// Thin / duplicate / keyword-stuffing / freshness signals per page.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";

export interface QualityIssue { code: string; severity: "low" | "medium" | "high"; detail?: string }
export interface PageQualityReport {
    url: string;
    word_count: number;
    issues: QualityIssue[];
    quality_score: number;          // 0-100
}

const THIN_THRESHOLD = 300;

function shingleSet(text: string, n: number = 5): Set<string> {
    const tokens = text.toLowerCase().split(/\s+/).filter(Boolean);
    const out = new Set<string>();
    for (let i = 0; i + n <= tokens.length; i++) {
        out.add(tokens.slice(i, i + n).join(" "));
    }
    return out;
}

function jaccard(a: Set<string>, b: Set<string>): number {
    if (a.size === 0 && b.size === 0) return 1;
    let intersect = 0;
    for (const s of a) if (b.has(s)) intersect++;
    return intersect / (a.size + b.size - intersect);
}

function topKeyword(text: string): { kw: string; count: number; total: number } {
    const tokens = text.toLowerCase().match(/[a-z]{3,}/g) ?? [];
    const stop = new Set(["the", "and", "for", "with", "that", "this", "from", "have", "are", "but", "you", "your", "not", "all"]);
    const freq = new Map<string, number>();
    for (const t of tokens) if (!stop.has(t)) freq.set(t, (freq.get(t) ?? 0) + 1);
    let best = ""; let n = 0;
    for (const [k, v] of freq) if (v > n) { best = k; n = v; }
    return { kw: best, count: n, total: tokens.length };
}

export function analyzePage(page: ParsedPage, others: ParsedPage[]): PageQualityReport {
    const issues: QualityIssue[] = [];
    const text = page.text_excerpt;

    if (page.word_count < THIN_THRESHOLD) {
        issues.push({ code: "thin_content", severity: "high",
            detail: `${page.word_count} words (min ${THIN_THRESHOLD})` });
    }

    // Keyword stuffing: top non-stopword > 3% density
    const top = topKeyword(text);
    if (top.total > 100) {
        const density = top.count / top.total;
        if (density > 0.03) {
            issues.push({ code: "keyword_stuffing", severity: "high",
                detail: `"${top.kw}" at ${(density * 100).toFixed(1)}%` });
        }
    }

    // Duplicate content across own site (Jaccard 5-gram > 0.6)
    const mine = shingleSet(text);
    for (const o of others) {
        if (o.url === page.url) continue;
        const theirs = shingleSet(o.text_excerpt);
        const j = jaccard(mine, theirs);
        if (j > 0.6) {
            issues.push({ code: "duplicate_content", severity: "medium",
                detail: `${(j * 100).toFixed(0)}% similar to ${o.url}` });
            break;
        }
    }

    // External links to authoritative sources (heuristic: at least one outbound link)
    const externalLinks = page.links.filter(l => !l.internal && l.href.startsWith("http"));
    if (externalLinks.length === 0 && page.word_count > 500) {
        issues.push({ code: "no_citations", severity: "low",
            detail: "long article has no external references" });
    }

    // Reading level too high (>14 = graduate-level, dense reading)
    if (page.reading_level > 14) {
        issues.push({ code: "reading_level_too_high", severity: "low",
            detail: `Flesch-Kincaid grade ${page.reading_level.toFixed(1)}` });
    }

    // Score: start at 100, subtract by severity
    let score = 100;
    for (const i of issues) {
        score -= i.severity === "high" ? 25 : i.severity === "medium" ? 12 : 4;
    }
    score = Math.max(0, score);

    return { url: page.url, word_count: page.word_count, issues, quality_score: score };
}

export class ContentQualityAnalyzer extends AgentBase {
    readonly id = "content_quality";
    readonly name = "Content Quality Analyzer";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const parsed = (input.parsed as ParsedPage[] | undefined) ?? [];
        if (parsed.length === 0) return { ok: false, error: "no parsed pages" };
        const reports = parsed.map(p => analyzePage(p, parsed));
        const siteScore = Math.round(reports.reduce((s, r) => s + r.quality_score, 0) / reports.length);
        return { ok: true, data: { reports, site_quality_score: siteScore } };
    }
}
