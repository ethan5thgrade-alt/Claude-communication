// 015 — Core Web Vitals Estimator (proxy without Lighthouse).
// Uses parsed signals as heuristic proxies for LCP / FID / CLS / TTFB.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";

export type CwvGrade = "green" | "yellow" | "red";

export interface CwvEstimate {
    url: string;
    lcp_grade: CwvGrade;
    fid_grade: CwvGrade;
    cls_grade: CwvGrade;
    ttfb_grade: CwvGrade;
    overall_grade: CwvGrade;
    recommendations: string[];
}

function gradeTtfb(ms: number): CwvGrade {
    if (ms < 600) return "green";
    if (ms < 1500) return "yellow";
    return "red";
}

export function estimate(page: ParsedPage, responseTimeMs: number): CwvEstimate {
    // LCP proxy: render-blocking scripts + heavy hero image (no dimensions hint)
    const blockingScripts = page.render_blocking_scripts;
    const heroImage = page.images[0];
    const heroHasDims = heroImage ? !!(heroImage.width && heroImage.height) : true;
    const lcpRed = blockingScripts >= 3 || !heroHasDims;
    const lcp_grade: CwvGrade = lcpRed ? "red" : blockingScripts >= 1 ? "yellow" : "green";

    // FID proxy: total external scripts + inline scripts
    const totalScripts = page.scripts.length;
    const fid_grade: CwvGrade = totalScripts >= 15 ? "red" : totalScripts >= 8 ? "yellow" : "green";

    // CLS proxy: images without dimensions
    const imgsNoDim = page.images.filter(i => !i.width || !i.height).length;
    const cls_grade: CwvGrade =
        imgsNoDim >= 5 ? "red" : imgsNoDim >= 2 ? "yellow" : "green";

    const ttfb_grade = gradeTtfb(responseTimeMs);

    const grades = [lcp_grade, fid_grade, cls_grade, ttfb_grade];
    const worst: CwvGrade = grades.includes("red") ? "red" : grades.includes("yellow") ? "yellow" : "green";

    const recommendations: string[] = [];
    if (lcpRed) recommendations.push("Defer non-critical scripts + add dimensions to hero image");
    if (totalScripts >= 8) recommendations.push("Audit and remove unused third-party scripts");
    if (imgsNoDim >= 2) recommendations.push(`Add explicit width/height to ${imgsNoDim} images`);
    if (responseTimeMs >= 1500) recommendations.push("Optimize TTFB (slow server response)");
    if (page.external_stylesheets >= 4) recommendations.push("Bundle/inline critical CSS");

    return {
        url: page.url,
        lcp_grade,
        fid_grade,
        cls_grade,
        ttfb_grade,
        overall_grade: worst,
        recommendations,
    };
}

export class CwvEstimator extends AgentBase {
    readonly id = "cwv_estimator";
    readonly name = "Core Web Vitals Estimator";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const parsed = (input.parsed as ParsedPage[] | undefined) ?? [];
        const rtMap = (input.response_times as Record<string, number> | undefined) ?? {};
        if (parsed.length === 0) return { ok: false, error: "no parsed pages" };
        const estimates = parsed.map(p => estimate(p, rtMap[p.url] ?? 500));
        return { ok: true, data: { estimates, count: estimates.length } };
    }
}
