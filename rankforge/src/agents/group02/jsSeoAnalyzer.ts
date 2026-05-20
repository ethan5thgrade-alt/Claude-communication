// 014 — JavaScript SEO Analyzer.
// Detects content that only exists after JS runs. Compares raw vs rendered HTML.

import { AgentBase } from "../../core/AgentBase.ts";
import { parseHTML } from "../../core/html.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface JsSeoReport {
    raw_word_count: number;
    rendered_word_count: number;
    word_count_delta_pct: number;     // 0 = identical
    raw_link_count: number;
    rendered_link_count: number;
    raw_meta_count: number;
    rendered_meta_count: number;
    raw_h1: string | null;
    rendered_h1: string | null;
    noscript_present: boolean;
    js_only_content_risk: "low" | "medium" | "high";
    findings: string[];
}

export function compare(rawHtml: string, renderedHtml: string | null): JsSeoReport {
    const raw = parseHTML(rawHtml);
    const rendered = renderedHtml ? parseHTML(renderedHtml) : raw;
    const findings: string[] = [];

    const rawH1 = raw.headings.find(h => h.level === 1)?.text ?? null;
    const renderedH1 = rendered.headings.find(h => h.level === 1)?.text ?? null;
    const wordsDelta = rendered.word_count > 0
        ? Math.abs(rendered.word_count - raw.word_count) / rendered.word_count
        : 0;

    if (raw.word_count < 100 && rendered.word_count > 500) {
        findings.push("Most content is JS-rendered — Googlebot may miss it");
    }
    if (raw.links.filter(l => l.internal).length < 3 && rendered.links.filter(l => l.internal).length > 5) {
        findings.push("Navigation appears to be JS-rendered");
    }
    if (raw.metas.length < rendered.metas.length - 2) {
        findings.push("Meta tags are JS-injected (use SSR for SEO-critical tags)");
    }
    if (!rawH1 && renderedH1) {
        findings.push("H1 is JS-injected — search engines may not see it");
    }

    const noscript = /<noscript[\s>]/i.test(rawHtml);

    let risk: "low" | "medium" | "high" = "low";
    if (wordsDelta > 0.5) risk = "high";
    else if (wordsDelta > 0.2) risk = "medium";
    if (findings.length >= 3) risk = "high";

    return {
        raw_word_count: raw.word_count,
        rendered_word_count: rendered.word_count,
        word_count_delta_pct: wordsDelta * 100,
        raw_link_count: raw.links.length,
        rendered_link_count: rendered.links.length,
        raw_meta_count: raw.metas.length,
        rendered_meta_count: rendered.metas.length,
        raw_h1: rawH1,
        rendered_h1: renderedH1,
        noscript_present: noscript,
        js_only_content_risk: risk,
        findings,
    };
}

export class JsSeoAnalyzer extends AgentBase {
    readonly id = "js_seo_analyzer";
    readonly name = "JavaScript SEO Analyzer";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const raw = input.raw_html as string | undefined;
        const rendered = input.rendered_html as string | undefined;
        if (!raw) return { ok: false, error: "raw_html required" };
        const report = compare(raw, rendered ?? null);
        return { ok: true, data: report };
    }
}
