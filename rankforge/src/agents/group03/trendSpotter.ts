// 035 — Trending Keyword Spotter.
// Heuristic emerging-trend detector. Compares input keyword candidates against
// a niche-aware trend signal list + accepts external recent_signals.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface TrendCandidate {
    keyword: string;
    mentions_last_30d?: number;
    mentions_prior_30d?: number;
}

export interface TrendOut {
    keyword: string;
    trending: boolean;
    score: number;            // 0-100
    velocity: number;         // pct growth
    reason: string;
}

// Generic emerging-trend tokens (would be niche-augmented in production)
const TREND_TOKENS = [
    "ai", "chatgpt", "llm", "agent", "gpt", "copilot",
    "ev", "tesla", "electric", "battery",
    "tiktok", "shorts", "reels",
    "ozempic", "glp-1", "wegovy",
    "vibe coding", "claude", "anthropic",
];

export function scoreTrend(c: TrendCandidate, niche: string[] = []): TrendOut {
    const kw = c.keyword.toLowerCase();
    let score = 0;
    let velocity = 0;
    const reasons: string[] = [];

    if (TREND_TOKENS.some(t => kw.includes(t))) {
        score += 40;
        reasons.push("trend_token");
    }
    if (niche.some(n => kw.includes(n.toLowerCase()))) {
        score += 20;
        reasons.push("niche_match");
    }
    if (typeof c.mentions_last_30d === "number" && typeof c.mentions_prior_30d === "number") {
        const prior = Math.max(1, c.mentions_prior_30d);
        velocity = Math.round(((c.mentions_last_30d - prior) / prior) * 100);
        if (velocity >= 200) { score += 40; reasons.push("explosive_growth"); }
        else if (velocity >= 50) { score += 25; reasons.push("strong_growth"); }
        else if (velocity >= 10) { score += 10; reasons.push("moderate_growth"); }
    }
    score = Math.max(0, Math.min(100, score));
    return {
        keyword: c.keyword,
        trending: score >= 40,
        score,
        velocity,
        reason: reasons.join("+") || "no_signal",
    };
}

export class TrendSpotter extends AgentBase {
    readonly id = "trend_spotter";
    readonly name = "Trending Keyword Spotter";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const candidates = input.candidates as TrendCandidate[] | undefined;
        if (!Array.isArray(candidates) || candidates.length === 0) {
            return { ok: false, error: "candidates array required" };
        }
        const niche = (input.niche_tokens as string[] | undefined) ?? [];
        const scored = candidates.map(c => scoreTrend(c, niche));
        const trending = scored.filter(s => s.trending).sort((a, b) => b.score - a.score);
        return {
            ok: true,
            data: {
                scored,
                trending,
                alert_count: trending.length,
            },
        };
    }
}
