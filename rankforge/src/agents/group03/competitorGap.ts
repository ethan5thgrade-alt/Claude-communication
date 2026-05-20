// 029 — Competitor Keyword Gap Agent.
// Compares our covered keywords vs each competitor's topics; finds gaps and
// prioritizes by (volume estimate) × (compete-ability score).

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface CompetitorTopicSet {
    domain: string;
    topics: string[];
    estimated_da?: number;
    volume_hints?: Record<string, number>;
}

export interface GapKeyword {
    keyword: string;
    competitor: string;
    competitor_volume_estimate: number;
    compete_ability: number;
    priority_score: number;
}

function normalize(s: string): string {
    return s.toLowerCase().trim().replace(/\s+/g, " ");
}

function competeAbility(ourDa: number, theirDa: number): number {
    const gap = ourDa - theirDa;
    return Math.max(0, Math.min(1, 0.5 + gap / 100));
}

export function findGaps(
    ourKeywords: string[],
    competitors: CompetitorTopicSet[],
    ourDa: number = 20,
): GapKeyword[] {
    const ourSet = new Set(ourKeywords.map(normalize));
    const gaps: GapKeyword[] = [];
    for (const comp of competitors) {
        const ability = competeAbility(ourDa, comp.estimated_da ?? 40);
        for (const t of comp.topics) {
            const norm = normalize(t);
            if (ourSet.has(norm)) continue;
            const volume = comp.volume_hints?.[norm]
                ?? comp.volume_hints?.[t]
                ?? Math.max(10, 100 - norm.length);
            const priority = volume * ability;
            gaps.push({
                keyword: norm,
                competitor: comp.domain,
                competitor_volume_estimate: volume,
                compete_ability: Math.round(ability * 100) / 100,
                priority_score: Math.round(priority * 100) / 100,
            });
        }
    }
    const bestByKw = new Map<string, GapKeyword>();
    for (const g of gaps) {
        const prev = bestByKw.get(g.keyword);
        if (!prev || g.priority_score > prev.priority_score) bestByKw.set(g.keyword, g);
    }
    return Array.from(bestByKw.values()).sort((a, b) => b.priority_score - a.priority_score);
}

export class CompetitorGap extends AgentBase {
    readonly id = "competitor_gap";
    readonly name = "Competitor Keyword Gap Agent";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const ours = (input.our_keywords as string[] | undefined)
            ?? (input.keywords as string[] | undefined)
            ?? [];
        const competitors = (input.competitors as CompetitorTopicSet[] | undefined) ?? [];
        if (competitors.length === 0) return { ok: false, error: "competitors required" };
        const ourDa = (input.our_da as number | undefined) ?? 20;
        const gaps = findGaps(ours, competitors, ourDa);
        const limit = (input.limit as number | undefined) ?? 200;
        const top = gaps.slice(0, limit);
        return { ok: true, data: { gaps: top, count: top.length, total_found: gaps.length } };
    }
}
