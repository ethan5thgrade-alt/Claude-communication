// 034 — Seasonal Keyword Detector.
// Flags seasonal keywords + identifies peak month, recommends publish window 6-8 wks early.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface SeasonalIn { keyword: string }

export interface SeasonalOut {
    keyword: string;
    is_seasonal: boolean;
    peak_month: number | null;      // 1-12
    publish_month: number | null;   // 6-8 weeks before peak
    pattern: string | null;
}

interface Pattern { name: string; peakMonth: number; tokens: string[] }

const PATTERNS: Pattern[] = [
    { name: "winter_heating", peakMonth: 11, tokens: ["furnace", "heating", "heat pump", "boiler", "winterize"] },
    { name: "summer_cooling", peakMonth: 5, tokens: ["air conditioner", "ac repair", "ac install", "cooling", "hvac"] },
    { name: "spring_lawn", peakMonth: 3, tokens: ["lawn", "mower", "fertilizer", "garden", "landscaping"] },
    { name: "fall_yard", peakMonth: 9, tokens: ["leaf", "gutter", "rake", "mulch"] },
    { name: "tax_season", peakMonth: 3, tokens: ["tax", "irs", "deduction", "filing"] },
    { name: "holiday_gifts", peakMonth: 11, tokens: ["gift", "christmas", "holiday", "stocking"] },
    { name: "halloween", peakMonth: 9, tokens: ["halloween", "costume", "pumpkin"] },
    { name: "back_to_school", peakMonth: 7, tokens: ["back to school", "school supplies", "backpack"] },
    { name: "valentines", peakMonth: 1, tokens: ["valentine", "valentines"] },
    { name: "mothers_day", peakMonth: 4, tokens: ["mother's day", "mothers day", "mom gift"] },
    { name: "fathers_day", peakMonth: 5, tokens: ["father's day", "fathers day", "dad gift"] },
    { name: "summer_travel", peakMonth: 5, tokens: ["vacation", "travel", "summer trip", "beach"] },
    { name: "pool_open", peakMonth: 4, tokens: ["pool open", "pool maintenance", "pool cleaning"] },
];

export function detectSeasonal(keyword: string): SeasonalOut {
    const kw = keyword.toLowerCase();
    for (const p of PATTERNS) {
        if (p.tokens.some(t => kw.includes(t))) {
            // publish month = peak - 2 (6-8 wks earlier)
            let publish = p.peakMonth - 2;
            if (publish <= 0) publish += 12;
            return {
                keyword,
                is_seasonal: true,
                peak_month: p.peakMonth,
                publish_month: publish,
                pattern: p.name,
            };
        }
    }
    return { keyword, is_seasonal: false, peak_month: null, publish_month: null, pattern: null };
}

export class SeasonalDetector extends AgentBase {
    readonly id = "seasonal_detector";
    readonly name = "Seasonal Keyword Detector";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = input.keywords as (string | SeasonalIn)[] | undefined;
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords array required" };
        }
        const currentMonth = (input.current_month as number | undefined)
            ?? new Date().getUTCMonth() + 1;
        const results = keywords.map(k => detectSeasonal(typeof k === "string" ? k : k.keyword));
        const seasonal = results.filter(r => r.is_seasonal);
        const upcoming = seasonal.filter(r => {
            if (r.publish_month == null) return false;
            const diff = (r.publish_month - currentMonth + 12) % 12;
            return diff <= 2;
        });
        return {
            ok: true,
            data: {
                results,
                seasonal_count: seasonal.length,
                upcoming_publish: upcoming,
            },
        };
    }
}
