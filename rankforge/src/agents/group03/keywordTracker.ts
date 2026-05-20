// 038 — Keyword Performance Tracker.
// Tracks which keywords have published posts (is_used), reports cluster coverage.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface TrackedKeyword {
    keyword: string;
    cluster?: string;
    is_used?: boolean;
    post_url?: string | null;
    gsc_impressions?: number;
    gsc_clicks?: number;
}

export interface ClusterCoverage {
    cluster: string;
    total: number;
    used: number;
    coverage_pct: number;
}

export interface TrackerOut {
    updated: TrackedKeyword[];
    cluster_coverage: ClusterCoverage[];
    gaining_traction: TrackedKeyword[];
    coverage_pct: number;
}

function normalize(s: string): string {
    return s.toLowerCase().trim();
}

export function track(
    keywords: TrackedKeyword[],
    publishedKeywords: string[],
): TrackerOut {
    const published = new Set(publishedKeywords.map(normalize));
    const updated = keywords.map(k => ({
        ...k,
        is_used: published.has(normalize(k.keyword)) || Boolean(k.is_used),
    }));

    // Per-cluster coverage
    const clusterMap = new Map<string, { total: number; used: number }>();
    for (const k of updated) {
        const c = k.cluster ?? "(unclustered)";
        const entry = clusterMap.get(c) ?? { total: 0, used: 0 };
        entry.total++;
        if (k.is_used) entry.used++;
        clusterMap.set(c, entry);
    }
    const cluster_coverage: ClusterCoverage[] = Array.from(clusterMap.entries()).map(
        ([cluster, v]) => ({
            cluster,
            total: v.total,
            used: v.used,
            coverage_pct: v.total === 0 ? 0 : Math.round((v.used / v.total) * 100),
        }),
    );

    // Gaining traction: has clicks > 0 OR impressions > 100
    const gaining_traction = updated.filter(k =>
        (k.gsc_clicks ?? 0) > 0 || (k.gsc_impressions ?? 0) > 100,
    );

    const totalUsed = updated.filter(k => k.is_used).length;
    const coverage_pct = updated.length === 0 ? 0 : Math.round((totalUsed / updated.length) * 100);

    return { updated, cluster_coverage, gaining_traction, coverage_pct };
}

export class KeywordTracker extends AgentBase {
    readonly id = "keyword_tracker";
    readonly name = "Keyword Performance Tracker";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = input.keywords as TrackedKeyword[] | undefined;
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords array required" };
        }
        const published = (input.published_keywords as string[] | undefined) ?? [];
        const result = track(keywords, published);
        return { ok: true, data: result };
    }
}
