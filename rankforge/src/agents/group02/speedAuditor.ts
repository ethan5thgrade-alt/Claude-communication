// 021 — Site Speed Deep Auditor.
// Resource-level page-speed signals + prioritized recommendations.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";
import type { CrawledPage } from "./siteCrawler.ts";

export interface SpeedFinding {
    code: string;
    severity: "low" | "medium" | "high";
    impact_score: number;     // 0-100 — used to sort recommendations
    detail: string;
}

export interface SpeedReport {
    url: string;
    page_weight_bytes: number;
    http_request_estimate: number;
    findings: SpeedFinding[];
    weighted_score: number;   // 100 = great, 0 = terrible
}

function auditOne(parsed: ParsedPage, crawled?: CrawledPage): SpeedReport {
    const findings: SpeedFinding[] = [];
    const bytes = crawled?.bytes ?? 0;
    // request count ~ images + scripts + stylesheets + 1 (HTML)
    const requestCount = parsed.images.length + parsed.scripts.length + parsed.external_stylesheets + 1;

    if (bytes > 2_500_000) {
        findings.push({
            code: "page_too_heavy",
            severity: "high",
            impact_score: 90,
            detail: `${(bytes / 1_000_000).toFixed(1)}MB (target <1.5MB)`,
        });
    }

    if (parsed.render_blocking_scripts >= 3) {
        findings.push({
            code: "many_render_blocking_scripts",
            severity: "high",
            impact_score: 85,
            detail: `${parsed.render_blocking_scripts} blocking scripts in <head>`,
        });
    }

    const nonWebpImages = parsed.images.filter(i =>
        i.src && !/\.(webp|avif)(\?|$)/i.test(i.src) && /\.(jpe?g|png)(\?|$)/i.test(i.src)
    ).length;
    if (nonWebpImages >= 5) {
        findings.push({
            code: "images_not_webp",
            severity: "medium",
            impact_score: 60,
            detail: `${nonWebpImages} JPEG/PNG images (use WebP/AVIF)`,
        });
    }

    const noLazy = parsed.images.filter(i => i.loading !== "lazy").length;
    if (parsed.images.length >= 6 && noLazy / parsed.images.length > 0.5) {
        findings.push({
            code: "missing_lazy_loading",
            severity: "medium",
            impact_score: 55,
            detail: `${noLazy} of ${parsed.images.length} images lack loading="lazy"`,
        });
    }

    const sansDimsCount = parsed.images.filter(i => !i.width || !i.height).length;
    if (sansDimsCount >= 3) {
        findings.push({
            code: "images_missing_dimensions",
            severity: "medium",
            impact_score: 50,
            detail: `${sansDimsCount} images without width/height (causes CLS)`,
        });
    }

    if (parsed.external_stylesheets >= 5) {
        findings.push({
            code: "too_many_stylesheets",
            severity: "medium",
            impact_score: 45,
            detail: `${parsed.external_stylesheets} external stylesheets`,
        });
    }

    if (requestCount > 80) {
        findings.push({
            code: "too_many_requests",
            severity: "high",
            impact_score: 75,
            detail: `~${requestCount} HTTP requests`,
        });
    }

    const ttfb = crawled?.response_time_ms ?? 0;
    if (ttfb > 1500) {
        findings.push({
            code: "slow_ttfb",
            severity: "high",
            impact_score: 80,
            detail: `${ttfb}ms TTFB (target <600ms)`,
        });
    }

    // No cache-control on a clearly-cacheable resource is a smell but we
    // can't see response headers here without the crawled page. Skip.

    // Score: start at 100, deduct by impact score
    let score = 100;
    for (const f of findings) {
        score -= f.severity === "high" ? Math.min(20, f.impact_score / 5) :
                 f.severity === "medium" ? 8 : 3;
    }
    score = Math.max(0, Math.round(score));

    findings.sort((a, b) => b.impact_score - a.impact_score);

    return {
        url: parsed.url,
        page_weight_bytes: bytes,
        http_request_estimate: requestCount,
        findings,
        weighted_score: score,
    };
}

export class SpeedAuditor extends AgentBase {
    readonly id = "speed_auditor";
    readonly name = "Site Speed Deep Auditor";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const parsed = (input.parsed as ParsedPage[] | undefined) ?? [];
        const pagesMap = new Map<string, CrawledPage>();
        for (const p of ((input.pages as CrawledPage[] | undefined) ?? [])) {
            pagesMap.set(p.final_url, p);
        }
        if (parsed.length === 0) return { ok: false, error: "no parsed pages" };
        const reports = parsed.map(p => auditOne(p, pagesMap.get(p.final_url)));
        const siteScore = Math.round(reports.reduce((s, r) => s + r.weighted_score, 0) / reports.length);
        return { ok: true, data: { reports, site_score: siteScore } };
    }
}
