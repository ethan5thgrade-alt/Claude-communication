// 039 — Content Strategy Planner.
// Sequences a batch of briefs from prioritized clusters: pillar first,
// supporting next, monthly cap enforced, seasonal/trending boosts applied.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface PlannerCluster {
    theme: string;
    pillar: string;
    supporting: string[];
    total_volume?: number;
    completion_pct?: number;
    priority?: number;
}

export interface ContentBrief {
    keyword: string;
    role: "pillar" | "supporting";
    theme: string;
    format: "blog" | "howto" | "listicle" | "comparison" | "local";
    writer_agent: string;
    priority: number;
    sequence: number;
    seasonal_boost: boolean;
    trending_boost: boolean;
}

const WRITERS: Record<ContentBrief["format"], string> = {
    blog: "blog_writer",
    howto: "howto_writer",
    listicle: "listicle_writer",
    comparison: "comparison_writer",
    local: "local_page_writer",
};

function classifyFormat(keyword: string): ContentBrief["format"] {
    const k = keyword.toLowerCase();
    if (/\bhow to\b|\bhowto\b/.test(k)) return "howto";
    if (/\b\d+\s+(best|ways|tips|tools|ideas)\b|\bbest\b/.test(k)) return "listicle";
    if (/\bvs\.?\b|\balternatives?\b|\bcompare(d)?\b/.test(k)) return "comparison";
    if (/\bnear me\b|\bin [a-z\s]+\b/.test(k)) return "local";
    return "blog";
}

export class ContentPlanner extends AgentBase {
    readonly id = "content_planner";
    readonly name = "Content Strategy Planner";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const clusters = input.clusters as PlannerCluster[] | undefined;
        if (!Array.isArray(clusters) || clusters.length === 0) {
            return { ok: false, error: "clusters array required" };
        }
        const monthlyCap = (input.monthly_cap as number | undefined) ?? 20;
        const seasonal = new Set((input.seasonal_keywords as string[] | undefined) ?? []);
        const trending = new Set((input.trending_keywords as string[] | undefined) ?? []);

        const sorted = [...clusters].sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
        const briefs: ContentBrief[] = [];
        let seq = 0;

        for (const c of sorted) {
            if (briefs.length >= monthlyCap) break;
            const basePriority = c.priority ?? c.total_volume ?? 0;
            const pillarFmt = classifyFormat(c.pillar);
            const pSeasonal = seasonal.has(c.pillar);
            const pTrending = trending.has(c.pillar);
            briefs.push({
                keyword: c.pillar,
                role: "pillar",
                theme: c.theme,
                format: pillarFmt,
                writer_agent: WRITERS[pillarFmt],
                priority: basePriority + (pSeasonal ? 500 : 0) + (pTrending ? 250 : 0),
                sequence: seq++,
                seasonal_boost: pSeasonal,
                trending_boost: pTrending,
            });

            for (const s of c.supporting) {
                if (briefs.length >= monthlyCap) break;
                const fmt = classifyFormat(s);
                const sSeasonal = seasonal.has(s);
                const sTrending = trending.has(s);
                briefs.push({
                    keyword: s,
                    role: "supporting",
                    theme: c.theme,
                    format: fmt,
                    writer_agent: WRITERS[fmt],
                    priority: Math.round(basePriority * 0.5) + (sSeasonal ? 500 : 0) + (sTrending ? 250 : 0),
                    sequence: seq++,
                    seasonal_boost: sSeasonal,
                    trending_boost: sTrending,
                });
            }
        }

        return {
            ok: true,
            data: {
                briefs,
                brief_count: briefs.length,
                monthly_cap: monthlyCap,
                hit_cap: briefs.length >= monthlyCap,
            },
        };
    }
}
