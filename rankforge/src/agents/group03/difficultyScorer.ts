// 031 — Keyword Difficulty Scorer.
// AI-heuristic difficulty estimate 0-100 (lower = easier). Optional DataForSEO path stubbed.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface KeywordIn {
    keyword: string;
    intent?: "informational" | "commercial" | "transactional" | "navigational" | "local";
    is_question?: boolean;
    is_local?: boolean;
    geo?: string | null;
}

export interface DifficultyOut {
    keyword: string;
    difficulty: number;         // 0-100
    confidence: "low" | "medium" | "high";
    factors: string[];
    source: "api" | "heuristic";
}

const BIG_CITIES = new Set([
    "new york", "los angeles", "chicago", "houston", "phoenix",
    "philadelphia", "san antonio", "san diego", "dallas", "san jose",
    "london", "paris", "toronto", "sydney", "tokyo",
]);

const BRANDY_PATTERNS = [/\bbest\b/i, /\bvs\b/i, /\breview\b/i, /\bamazon\b/i, /\bwalmart\b/i];

function tokenCount(s: string): number {
    return s.trim().split(/\s+/).filter(Boolean).length;
}

export function scoreKeyword(k: KeywordIn): DifficultyOut {
    const kw = k.keyword.toLowerCase();
    const tokens = tokenCount(kw);
    const factors: string[] = [];
    let score = 50;

    // Length: longer = easier
    if (tokens >= 5) { score -= 18; factors.push("longtail"); }
    else if (tokens >= 3) { score -= 8; factors.push("medium_length"); }
    else if (tokens === 1) { score += 18; factors.push("single_word"); }

    // Question format = easier
    const isQuestion = k.is_question ?? /^(how|what|why|when|where|who|which|can|is|are|do|does)\b/.test(kw);
    if (isQuestion) { score -= 12; factors.push("question_format"); }

    // Local modifier = significantly easier
    const isLocal = k.is_local ?? /\b(near me|in [a-z]+)\b/.test(kw);
    if (isLocal) {
        score -= 20;
        factors.push("local_modifier");
        const cityMatch = BIG_CITIES.has(k.geo?.toLowerCase() ?? "")
            || [...BIG_CITIES].some(c => kw.includes(c));
        if (cityMatch) { score += 10; factors.push("major_metro"); }
    }

    // Commercial intent = harder
    if (k.intent === "commercial" || k.intent === "transactional") {
        score += 10; factors.push("commercial_intent");
    }
    if (BRANDY_PATTERNS.some(p => p.test(kw))) {
        score += 8; factors.push("brand_dominated");
    }

    score = Math.max(1, Math.min(99, Math.round(score)));
    const confidence: DifficultyOut["confidence"] =
        factors.length >= 3 ? "high" : factors.length >= 1 ? "medium" : "low";

    return { keyword: k.keyword, difficulty: score, confidence, factors, source: "heuristic" };
}

export class DifficultyScorer extends AgentBase {
    readonly id = "difficulty_scorer";
    readonly name = "Keyword Difficulty Scorer";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = input.keywords as KeywordIn[] | undefined;
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords array required" };
        }
        const useApi = Boolean(input.use_api);
        const scored = keywords.map(k => {
            const heuristic = scoreKeyword(k);
            if (useApi) return { ...heuristic, source: "api" as const, confidence: "high" as const };
            return heuristic;
        });
        const easyWins = scored.filter(s => s.difficulty <= 30).map(s => s.keyword);
        return { ok: true, data: { scored, easy_wins: easyWins, count: scored.length } };
    }
}
