// 023 — Master Keyword Orchestrator.
// Coordinates all 15 keyword sub-agents. Merges keyword lists, removes
// duplicates, produces a single unified keyword database for the site.

import { AgentBase } from "../../core/AgentBase.ts";
import { getAgent } from "../../core/registry.ts";
import type { AgentInput, AgentOutput, AgentTrigger } from "../../core/types.ts";

const SUBAGENT_IDS: string[] = [
    "seed_extractor",
    "keyword_expander",
    "longtail_miner",
    "question_miner",
    "local_keyword_agent",
    "competitor_gap",
    "intent_classifier",
    "difficulty_scorer",
    "volume_estimator",
    "cluster_builder",
    "seasonal_detector",
    "trend_spotter",
    "voice_optimizer",
    "paa_miner",
    "keyword_tracker",
];

export interface UnifiedKeyword {
    keyword: string;
    sources: string[];
}

function pluckKeywords(data: unknown): string[] {
    if (!data || typeof data !== "object") return [];
    const d = data as Record<string, unknown>;
    const out: string[] = [];
    const collect = (val: unknown): void => {
        if (typeof val === "string") { out.push(val); return; }
        if (Array.isArray(val)) {
            for (const v of val) {
                if (typeof v === "string") out.push(v);
                else if (v && typeof v === "object" && "keyword" in v && typeof (v as { keyword: unknown }).keyword === "string") {
                    out.push((v as { keyword: string }).keyword);
                }
            }
        }
    };
    for (const key of ["keywords", "seeds", "expanded", "longtails", "questions", "local_keywords", "gaps", "classified"]) {
        if (key in d) collect(d[key]);
    }
    return out;
}

export function mergeKeywords(perAgent: Record<string, string[]>): UnifiedKeyword[] {
    const map = new Map<string, Set<string>>();
    for (const [agent, list] of Object.entries(perAgent)) {
        for (const raw of list) {
            const k = raw.toLowerCase().trim();
            if (!k) continue;
            if (!map.has(k)) map.set(k, new Set());
            map.get(k)!.add(agent);
        }
    }
    return Array.from(map.entries())
        .map(([keyword, sources]) => ({ keyword, sources: Array.from(sources).sort() }))
        .sort((a, b) => b.sources.length - a.sources.length || a.keyword.localeCompare(b.keyword));
}

export class KeywordOrchestrator extends AgentBase {
    readonly id = "keyword_orchestrator";
    readonly name = "Master Keyword Orchestrator";
    readonly group = 3;
    readonly version = "1.0.0";

    nextAgents(_output: AgentOutput): AgentTrigger[] {
        return [];
    }

    async run(input: AgentInput): Promise<AgentOutput> {
        const seeds = (input.seeds as string[] | undefined) ?? [];
        const pages = input.pages;
        if (seeds.length === 0 && !pages) {
            return { ok: false, error: "seeds or pages required" };
        }

        const requested = (input.agents as string[] | undefined) ?? SUBAGENT_IDS;
        const perAgent: Record<string, string[]> = {};
        const ran: string[] = [];
        const skipped: string[] = [];

        for (const id of requested) {
            if (id === this.id) continue;
            const agent = getAgent(id);
            if (!agent) { skipped.push(id); continue; }
            const subInput: AgentInput = { ...input, seeds, keywords: seeds, triggered_by: this.id };
            try {
                const out = await agent.run(subInput);
                if (out.ok && out.data) {
                    perAgent[id] = pluckKeywords(out.data);
                    ran.push(id);
                } else {
                    skipped.push(id);
                }
            } catch {
                skipped.push(id);
            }
        }

        const unified = mergeKeywords(perAgent);
        return {
            ok: true,
            data: {
                unified_keywords: unified,
                total_unique: unified.length,
                agents_ran: ran,
                agents_skipped: skipped,
                per_agent_counts: Object.fromEntries(Object.entries(perAgent).map(([k, v]) => [k, v.length])),
            },
        };
    }
}
