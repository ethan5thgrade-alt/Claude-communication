// Group 3 — Keyword Intelligence (agents 023-038).

import { AgentBase } from "../../core/AgentBase.ts";
import { registerAgent } from "../../core/registry.ts";
import { KeywordOrchestrator } from "./keywordOrchestrator.ts";
import { SeedExtractor } from "./seedExtractor.ts";
import { KeywordExpander } from "./keywordExpander.ts";
import { LongTailMiner } from "./longtailMiner.ts";
import { QuestionMiner } from "./questionMiner.ts";
import { LocalKeywordAgent } from "./localKeywordAgent.ts";
import { CompetitorGap } from "./competitorGap.ts";
import { IntentClassifier } from "./intentClassifier.ts";
import { DifficultyScorer } from "./difficultyScorer.ts";
import { VolumeEstimator } from "./volumeEstimator.ts";
import { ClusterBuilder } from "./clusterBuilder.ts";
import { SeasonalDetector } from "./seasonalDetector.ts";
import { TrendSpotter } from "./trendSpotter.ts";
import { VoiceOptimizer } from "./voiceOptimizer.ts";
import { PaaMiner } from "./paaMiner.ts";
import { KeywordTracker } from "./keywordTracker.ts";

export * from "./keywordOrchestrator.ts";
export * from "./seedExtractor.ts";
export * from "./keywordExpander.ts";
export * from "./longtailMiner.ts";
export * from "./questionMiner.ts";
export * from "./localKeywordAgent.ts";
export * from "./competitorGap.ts";
export * from "./intentClassifier.ts";

export function registerGroup03(): Record<string, AgentBase> {
    const all: Record<string, AgentBase> = {
        keyword_orchestrator: new KeywordOrchestrator(),
        seed_extractor: new SeedExtractor(),
        keyword_expander: new KeywordExpander(),
        longtail_miner: new LongTailMiner(),
        question_miner: new QuestionMiner(),
        local_keyword_agent: new LocalKeywordAgent(),
        competitor_gap: new CompetitorGap(),
        intent_classifier: new IntentClassifier(),
        difficulty_scorer: new DifficultyScorer(),
        volume_estimator: new VolumeEstimator(),
        cluster_builder: new ClusterBuilder(),
        seasonal_detector: new SeasonalDetector(),
        trend_spotter: new TrendSpotter(),
        voice_optimizer: new VoiceOptimizer(),
        paa_miner: new PaaMiner(),
        keyword_tracker: new KeywordTracker(),
    };
    for (const a of Object.values(all)) registerAgent(a);
    return all;
}
