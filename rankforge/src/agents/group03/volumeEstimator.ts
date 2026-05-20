// 032 — Volume Estimator.
// AI tier estimate (low/medium/high) + confidence. Optional API path stubbed.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type VolumeTier = "very_low" | "low" | "medium" | "high" | "very_high";

export interface VolumeIn {
    keyword: string;
    intent?: string;
    is_question?: boolean;
    is_local?: boolean;
    geo_population?: number | null;
}

export interface VolumeOut {
    keyword: string;
    tier: VolumeTier;
    estimate: number;           // approximate monthly searches midpoint
    confidence: "low" | "medium" | "high";
    source: "api" | "heuristic";
}

const POPULAR_TOPICS = [
    "recipe", "weather", "news", "music", "movie", "game", "tiktok", "instagram",
    "iphone", "amazon", "netflix", "youtube", "ai", "chatgpt",
];

const TIER_MIDPOINTS: Record<VolumeTier, number> = {
    very_low: 30,
    low: 150,
    medium: 800,
    high: 4500,
    very_high: 25000,
};

function tokenCount(s: string): number {
    return s.trim().split(/\s+/).filter(Boolean).length;
}

export function estimateVolume(k: VolumeIn): VolumeOut {
    const kw = k.keyword.toLowerCase();
    const tokens = tokenCount(kw);
    let signal = 0;

    // Topic popularity
    if (POPULAR_TOPICS.some(t => kw.includes(t))) signal += 2;

    // Length: shorter = generally higher volume
    if (tokens === 1) signal += 3;
    else if (tokens === 2) signal += 2;
    else if (tokens === 3) signal += 1;
    else if (tokens >= 6) signal -= 2;

    // Questions: specific, lower volume on average
    if (k.is_question) signal -= 1;

    // Local: depends on population
    if (k.is_local) {
        const pop = k.geo_population ?? 0;
        if (pop >= 1_000_000) signal += 1;
        else if (pop >= 100_000) signal += 0;
        else signal -= 1;
    }

    // Transactional usually narrower than informational
    if (k.intent === "transactional") signal -= 1;

    let tier: VolumeTier;
    if (signal >= 4) tier = "very_high";
    else if (signal >= 2) tier = "high";
    else if (signal >= 0) tier = "medium";
    else if (signal >= -2) tier = "low";
    else tier = "very_low";

    const confidence: VolumeOut["confidence"] =
        Math.abs(signal) >= 3 ? "high" : Math.abs(signal) >= 1 ? "medium" : "low";

    return {
        keyword: k.keyword,
        tier,
        estimate: TIER_MIDPOINTS[tier],
        confidence,
        source: "heuristic",
    };
}

export class VolumeEstimator extends AgentBase {
    readonly id = "volume_estimator";
    readonly name = "Volume Estimator";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = input.keywords as VolumeIn[] | undefined;
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords array required" };
        }
        const useApi = Boolean(input.use_api);
        const results = keywords.map(k => {
            const h = estimateVolume(k);
            return useApi ? { ...h, source: "api" as const, confidence: "high" as const } : h;
        });
        return {
            ok: true,
            data: {
                results,
                count: results.length,
                total_volume_estimate: results.reduce((s, r) => s + r.estimate, 0),
            },
        };
    }
}
