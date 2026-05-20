// 033 — Topical Cluster Builder.
// Groups keywords into pillar + supporting clusters by token overlap.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface ClusterIn {
    keyword: string;
    volume?: number;
}

export interface Cluster {
    theme: string;
    pillar: string;
    supporting: string[];
    size: number;
    total_volume: number;
    completion_pct: number;
    priority: number;
}

const STOP = new Set([
    "the", "a", "an", "for", "to", "in", "of", "and", "or", "with", "by",
    "on", "at", "is", "are", "how", "what", "why", "when", "where", "do", "does",
    "vs", "best", "near", "me", "my", "your",
]);

function tokenize(s: string): string[] {
    return s.toLowerCase().match(/[a-z0-9]+/g)?.filter(t => !STOP.has(t) && t.length > 2) ?? [];
}

function overlap(a: string[], b: string[]): number {
    const setB = new Set(b);
    let n = 0;
    for (const t of a) if (setB.has(t)) n++;
    return n;
}

export function buildClusters(
    keywords: ClusterIn[],
    options: { existingPosts?: string[]; minOverlap?: number } = {},
): Cluster[] {
    if (keywords.length === 0) return [];
    const minOverlap = options.minOverlap ?? 1;
    const existing = new Set((options.existingPosts ?? []).map(p => p.toLowerCase()));

    // Sort by volume desc so highest-volume keywords seed clusters as pillars
    const sorted = [...keywords].sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0));
    const tokenMap = new Map<string, string[]>();
    for (const k of sorted) tokenMap.set(k.keyword, tokenize(k.keyword));

    const clusters: Cluster[] = [];
    const assigned = new Set<string>();

    for (const seed of sorted) {
        if (assigned.has(seed.keyword)) continue;
        const seedTokens = tokenMap.get(seed.keyword)!;
        if (seedTokens.length === 0) continue;
        const supporting: string[] = [];
        let volSum = seed.volume ?? 0;

        for (const cand of sorted) {
            if (cand.keyword === seed.keyword) continue;
            if (assigned.has(cand.keyword)) continue;
            const candTokens = tokenMap.get(cand.keyword)!;
            if (overlap(seedTokens, candTokens) >= minOverlap) {
                supporting.push(cand.keyword);
                volSum += cand.volume ?? 0;
                assigned.add(cand.keyword);
                if (supporting.length >= 15) break;
            }
        }
        assigned.add(seed.keyword);

        const themeToken = seedTokens[0] ?? seed.keyword.split(/\s+/)[0];
        const allInCluster = [seed.keyword, ...supporting];
        const covered = allInCluster.filter(k => existing.has(k.toLowerCase())).length;
        const completion = Math.round((covered / allInCluster.length) * 100);
        // Priority: high volume + low completion = high priority
        const priority = Math.round(volSum * (1 - completion / 100));

        clusters.push({
            theme: themeToken,
            pillar: seed.keyword,
            supporting,
            size: allInCluster.length,
            total_volume: volSum,
            completion_pct: completion,
            priority,
        });
    }

    return clusters.sort((a, b) => b.priority - a.priority);
}

export class ClusterBuilder extends AgentBase {
    readonly id = "cluster_builder";
    readonly name = "Topical Cluster Builder";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = input.keywords as ClusterIn[] | undefined;
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords array required" };
        }
        const existingPosts = (input.existing_posts as string[] | undefined) ?? [];
        const clusters = buildClusters(keywords, { existingPosts });
        return {
            ok: true,
            data: {
                clusters,
                cluster_count: clusters.length,
                keywords_clustered: clusters.reduce((s, c) => s + c.size, 0),
            },
        };
    }
}
