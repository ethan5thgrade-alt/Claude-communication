import { test } from "node:test";
import assert from "node:assert/strict";

import { DifficultyScorer, scoreKeyword } from "../src/agents/group03/difficultyScorer.ts";
import { VolumeEstimator, estimateVolume } from "../src/agents/group03/volumeEstimator.ts";
import { ClusterBuilder, buildClusters } from "../src/agents/group03/clusterBuilder.ts";
import { SeasonalDetector, detectSeasonal } from "../src/agents/group03/seasonalDetector.ts";
import { TrendSpotter, scoreTrend } from "../src/agents/group03/trendSpotter.ts";
import { VoiceOptimizer, toVoiceVariants } from "../src/agents/group03/voiceOptimizer.ts";
import { PaaMiner, minePaa } from "../src/agents/group03/paaMiner.ts";
import { KeywordTracker, track } from "../src/agents/group03/keywordTracker.ts";

test("DifficultyScorer scores local + question keywords easier than single-word commercial", () => {
    const local = scoreKeyword({ keyword: "plumber near me", is_local: true });
    const question = scoreKeyword({ keyword: "how to unclog a sink", is_question: true });
    const hard = scoreKeyword({ keyword: "insurance", intent: "commercial" });
    assert.ok(local.difficulty < hard.difficulty,
        `local ${local.difficulty} should be < commercial ${hard.difficulty}`);
    assert.ok(question.difficulty < hard.difficulty,
        `question ${question.difficulty} should be < commercial ${hard.difficulty}`);
    assert.ok(local.factors.includes("local_modifier"));
});

test("DifficultyScorer agent rejects empty input and returns easy_wins", async () => {
    const agent = new DifficultyScorer();
    const bad = await agent.run({});
    assert.equal(bad.ok, false);
    const out = await agent.run({
        keywords: [
            { keyword: "best laptop", intent: "commercial" },
            { keyword: "how to fix a leaky faucet at home", is_question: true },
            { keyword: "electrician near me", is_local: true },
        ],
    });
    assert.equal(out.ok, true);
    const data = out.data as { easy_wins: string[]; scored: { source: string }[] };
    assert.ok(data.easy_wins.length >= 1);
    assert.equal(data.scored[0].source, "heuristic");
});

test("VolumeEstimator returns tier and confidence", () => {
    const broad = estimateVolume({ keyword: "weather" });
    const niche = estimateVolume({
        keyword: "how to replace a vintage 1972 camaro carburetor gasket",
        is_question: true,
    });
    assert.ok(["high", "very_high"].includes(broad.tier));
    assert.ok(["very_low", "low"].includes(niche.tier));
    assert.ok(broad.estimate > niche.estimate);
    assert.ok(["low", "medium", "high"].includes(broad.confidence));
});

test("VolumeEstimator agent sums tier midpoints", async () => {
    const agent = new VolumeEstimator();
    const out = await agent.run({
        keywords: [{ keyword: "ai" }, { keyword: "chatgpt" }],
    });
    assert.equal(out.ok, true);
    const data = out.data as { total_volume_estimate: number; count: number };
    assert.equal(data.count, 2);
    assert.ok(data.total_volume_estimate > 0);
});

test("ClusterBuilder groups keywords sharing tokens into pillars", () => {
    const clusters = buildClusters([
        { keyword: "best espresso machine", volume: 5000 },
        { keyword: "espresso machine reviews", volume: 2000 },
        { keyword: "cheap espresso machine", volume: 800 },
        { keyword: "pour over coffee guide", volume: 3000 },
        { keyword: "pour over coffee technique", volume: 600 },
    ]);
    // Should produce 2 distinct clusters
    assert.ok(clusters.length >= 2);
    const espresso = clusters.find(c => c.pillar.includes("espresso"));
    assert.ok(espresso, "expected an espresso cluster");
    assert.ok(espresso!.supporting.length >= 1);
    // Pillar should be the highest-volume keyword in its cluster
    assert.equal(espresso!.pillar, "best espresso machine");
});

test("ClusterBuilder computes completion_pct from existing posts", async () => {
    const agent = new ClusterBuilder();
    const out = await agent.run({
        keywords: [
            { keyword: "dog training tips", volume: 1000 },
            { keyword: "dog training treats", volume: 500 },
        ],
        existing_posts: ["dog training tips"],
    });
    assert.equal(out.ok, true);
    const data = out.data as { clusters: { completion_pct: number }[] };
    assert.ok(data.clusters[0].completion_pct > 0);
});

test("SeasonalDetector flags heating, AC, and holiday gifts", () => {
    assert.equal(detectSeasonal("furnace tune up").is_seasonal, true);
    assert.equal(detectSeasonal("air conditioner repair").is_seasonal, true);
    assert.equal(detectSeasonal("holiday gift ideas").is_seasonal, true);
    assert.equal(detectSeasonal("javascript closures").is_seasonal, false);
    const heating = detectSeasonal("furnace tune up");
    assert.equal(heating.peak_month, 11);
    // publish_month = peak - 2 = September (9)
    assert.equal(heating.publish_month, 9);
});

test("SeasonalDetector agent surfaces upcoming publishes for given month", async () => {
    const agent = new SeasonalDetector();
    const out = await agent.run({
        keywords: ["furnace tune up", "lawn mower repair"],
        current_month: 9, // September -> publish month for furnace is Sept (peak Nov)
    });
    assert.equal(out.ok, true);
    const data = out.data as { upcoming_publish: unknown[]; seasonal_count: number };
    assert.ok(data.seasonal_count >= 1);
    assert.ok(data.upcoming_publish.length >= 1);
});

test("TrendSpotter flags growth-velocity + trend-token candidates", () => {
    const explosive = scoreTrend({
        keyword: "claude agent skills",
        mentions_last_30d: 800,
        mentions_prior_30d: 50,
    });
    const flat = scoreTrend({
        keyword: "ordinary garden hose",
        mentions_last_30d: 100,
        mentions_prior_30d: 100,
    });
    assert.equal(explosive.trending, true);
    assert.equal(flat.trending, false);
    assert.ok(explosive.score > flat.score);
});

test("VoiceOptimizer produces 3+ variants including near-me", () => {
    const v = toVoiceVariants("plumber");
    assert.ok(v.variants.length >= 3, `got ${v.variants.length} variants`);
    assert.ok(v.variants.some(s => s.includes("near me")));
    assert.ok(v.variants.some(s => s.startsWith("hey google")));
    assert.ok(v.short_answer_target.length > 0);
});

test("VoiceOptimizer agent handles question-form keywords", async () => {
    const agent = new VoiceOptimizer();
    const out = await agent.run({ keywords: ["how to brew coffee", "espresso machine"] });
    assert.equal(out.ok, true);
    const data = out.data as { total_variants: number; results: { variants: string[] }[] };
    assert.ok(data.total_variants >= 6);
    assert.ok(data.results[0].variants.every(v => v.length > 0));
});

test("PaaMiner outputs question-formatted strings", () => {
    const p = minePaa("solar panels");
    assert.ok(p.questions.length >= 5);
    // Every question ends with ? and starts with capital letter
    for (const q of p.questions) {
        assert.ok(q.endsWith("?"), `not a question: "${q}"`);
        assert.equal(q[0], q[0].toUpperCase());
    }
    assert.ok(p.questions.some(q => q.toLowerCase().includes("what is solar panels")));
});

test("PaaMiner agent caps per-keyword question count", async () => {
    const agent = new PaaMiner();
    const out = await agent.run({
        keywords: ["solar panels", "heat pumps"],
        max_per_keyword: 5,
    });
    assert.equal(out.ok, true);
    const data = out.data as { results: { questions: string[] }[]; total_questions: number };
    assert.equal(data.results[0].questions.length, 5);
    assert.equal(data.total_questions, 10);
});

test("KeywordTracker updates is_used and computes cluster coverage", () => {
    const r = track(
        [
            { keyword: "Dog Training Tips", cluster: "dog_training", is_used: false },
            { keyword: "dog training treats", cluster: "dog_training", is_used: false },
            { keyword: "cat grooming", cluster: "cat_care", is_used: false },
        ],
        ["dog training tips"],
    );
    assert.equal(r.updated[0].is_used, true);
    assert.equal(r.updated[1].is_used, false);
    const dog = r.cluster_coverage.find(c => c.cluster === "dog_training")!;
    assert.equal(dog.coverage_pct, 50);
    assert.ok(r.coverage_pct > 0);
});

test("KeywordTracker flags gaining-traction keywords from GSC signals", async () => {
    const agent = new KeywordTracker();
    const out = await agent.run({
        keywords: [
            { keyword: "kw a", gsc_impressions: 500, gsc_clicks: 10 },
            { keyword: "kw b", gsc_impressions: 5 },
        ],
        published_keywords: [],
    });
    assert.equal(out.ok, true);
    const data = out.data as { gaining_traction: { keyword: string }[] };
    assert.equal(data.gaining_traction.length, 1);
    assert.equal(data.gaining_traction[0].keyword, "kw a");
});
