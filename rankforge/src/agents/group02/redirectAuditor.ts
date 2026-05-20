// 022 — Redirect & Canonical Auditor.
// Detects chains, loops, 302-misuse, canonical conflicts, www/https consistency.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";
import type { CrawledPage } from "./siteCrawler.ts";

export interface RedirectIssue {
    code: string;
    severity: "low" | "medium" | "high" | "critical";
    detail: string;
    fix?: string;
}

export interface CanonicalConflict {
    page: string;
    canonical_target: string;
    target_canonical: string;
}

export interface RedirectReport {
    total_pages: number;
    chain_issues: RedirectIssue[];
    loop_count: number;
    misuse_302: number;
    canonical_conflicts: CanonicalConflict[];
    missing_self_canonical: string[];
    fix_map: { from: string; to: string; type: 301 }[];
}

export function detectLoops(chain: { url: string; status: number }[]): boolean {
    const seen = new Set<string>();
    for (const hop of chain) {
        if (seen.has(hop.url)) return true;
        seen.add(hop.url);
    }
    return false;
}

export function audit(pages: CrawledPage[], parsed: ParsedPage[]): RedirectReport {
    const issues: RedirectIssue[] = [];
    let loops = 0;
    let misuse302 = 0;
    const fixMap: { from: string; to: string; type: 301 }[] = [];

    for (const page of pages) {
        const chain = page.redirect_chain;
        if (chain.length >= 2) {
            issues.push({
                code: "long_redirect_chain",
                severity: "medium",
                detail: `${page.url} → ${chain.length} hops → ${page.final_url}`,
                fix: `301 ${page.url} → ${page.final_url} directly`,
            });
            fixMap.push({ from: page.url, to: page.final_url, type: 301 });
        }
        if (detectLoops([...chain, { url: page.final_url, status: page.status }])) {
            issues.push({
                code: "redirect_loop",
                severity: "critical",
                detail: `loop in chain for ${page.url}`,
            });
            loops++;
        }
        const has302 = chain.some(c => c.status === 302);
        if (has302) {
            issues.push({
                code: "misuse_302",
                severity: "medium",
                detail: `${page.url}: 302 redirect (use 301 to pass link equity)`,
                fix: "replace 302 with 301",
            });
            misuse302++;
        }
    }

    // Canonical conflicts: page A says canonical=B, page B says canonical=A (or anything ≠ B)
    const byUrl = new Map<string, ParsedPage>();
    for (const p of parsed) byUrl.set(p.final_url, p);

    const conflicts: CanonicalConflict[] = [];
    for (const page of parsed) {
        if (!page.canonical) continue;
        let canonAbs: string;
        try { canonAbs = new URL(page.canonical, page.final_url).href; } catch { continue; }
        if (canonAbs === page.final_url) continue;  // self-canonical, fine
        const target = byUrl.get(canonAbs);
        if (!target) continue;  // canonical points outside our crawl
        if (target.canonical) {
            let targetCanon: string;
            try { targetCanon = new URL(target.canonical, target.final_url).href; } catch { continue; }
            if (targetCanon !== canonAbs) {
                conflicts.push({
                    page: page.final_url,
                    canonical_target: canonAbs,
                    target_canonical: targetCanon,
                });
                issues.push({
                    code: "canonical_conflict",
                    severity: "high",
                    detail: `${page.final_url} canonicals to ${canonAbs} but ${canonAbs} canonicals to ${targetCanon}`,
                });
            }
        }
    }

    // Self-canonical missing
    const missingSelf = parsed.filter(p => {
        if (!p.canonical) return true;
        try {
            return new URL(p.canonical, p.final_url).href !== p.final_url;
        } catch { return true; }
    }).map(p => p.final_url);

    // www / https consistency: if some final_urls start with www and others don't,
    // or some are http and some https — flag.
    const hosts = new Set(parsed.map(p => {
        try { return new URL(p.final_url).host; } catch { return ""; }
    }));
    const wwwMixed = Array.from(hosts).some(h => h.startsWith("www.")) &&
                     Array.from(hosts).some(h => !h.startsWith("www.") && h);
    if (wwwMixed) {
        issues.push({
            code: "www_inconsistent",
            severity: "medium",
            detail: "Some URLs are www, others aren't — pick one and 301 the other",
        });
    }

    const schemes = new Set(parsed.map(p => {
        try { return new URL(p.final_url).protocol; } catch { return ""; }
    }));
    if (schemes.has("http:") && schemes.has("https:")) {
        issues.push({
            code: "http_https_inconsistent",
            severity: "high",
            detail: "Mixed http/https final URLs — force HTTPS site-wide",
        });
    }

    return {
        total_pages: pages.length,
        chain_issues: issues,
        loop_count: loops,
        misuse_302: misuse302,
        canonical_conflicts: conflicts,
        missing_self_canonical: missingSelf,
        fix_map: fixMap,
    };
}

export class RedirectAuditor extends AgentBase {
    readonly id = "redirect_auditor";
    readonly name = "Redirect & Canonical Auditor";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const pages = (input.pages as CrawledPage[] | undefined) ?? [];
        const parsed = (input.parsed as ParsedPage[] | undefined) ?? [];
        if (pages.length === 0 && parsed.length === 0) return { ok: false, error: "no pages" };
        const report = audit(pages, parsed);
        return { ok: true, data: report };
    }
}
