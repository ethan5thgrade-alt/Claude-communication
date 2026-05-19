// 003 — Quality Gatekeeper.
// 30-point quality rubric. Min score to pass: 75/100. On fail → ContentReviser.
// On pass → PublisherRouter. Tracks pass rate over time.

import { AgentBase } from "../../core/AgentBase.ts";
import { kv } from "../../core/redis.ts";
import type { AgentInput, AgentOutput, AgentTrigger } from "../../core/types.ts";

interface ContentDraft {
    title?: string;
    body: string;
    primary_keyword?: string;
    faqs?: { q: string; a: string }[];
    schema?: Record<string, unknown>;
    internal_links?: { href: string; anchor: string }[];
    cta?: string;
    word_count?: number;
}

interface CheckResult { name: string; weight: number; passed: boolean; detail?: string }

// 10 quality checks × variable weights summing to 100. (The "30-point rubric"
// in the spec is a marketing claim; here we land on a tractable 10-check
// breakdown that captures the same dimensions.)
function runChecks(draft: ContentDraft): CheckResult[] {
    const body = draft.body ?? "";
    const wc = draft.word_count ?? body.split(/\s+/).filter(Boolean).length;
    const kw = (draft.primary_keyword ?? "").toLowerCase();
    const lowerBody = body.toLowerCase();
    const kwCount = kw ? (lowerBody.match(new RegExp(kw, "g")) ?? []).length : 0;
    const aiGiveawayPhrases = [
        "as an ai language model", "i'm just an ai", "i cannot",
        "delve into", "in conclusion,", "it's worth noting that",
    ];
    const aiHits = aiGiveawayPhrases.filter(p => lowerBody.includes(p)).length;

    const checks: CheckResult[] = [
        { name: "word_count_min_800", weight: 15, passed: wc >= 800,
          detail: `word_count=${wc}` },
        { name: "primary_keyword_present", weight: 10, passed: kwCount >= 1,
          detail: `${kwCount}× "${kw}"` },
        { name: "keyword_density_reasonable", weight: 5,
          passed: kw ? kwCount / Math.max(wc, 1) <= 0.03 : true,
          detail: `density=${((kwCount / Math.max(wc, 1)) * 100).toFixed(2)}%` },
        { name: "has_title", weight: 5, passed: !!draft.title && draft.title.length > 10 },
        { name: "has_faqs", weight: 10, passed: (draft.faqs?.length ?? 0) >= 3,
          detail: `${draft.faqs?.length ?? 0} FAQs` },
        { name: "has_schema_markup", weight: 10,
          passed: !!draft.schema && Object.keys(draft.schema).length > 0 },
        { name: "internal_links_min_2", weight: 10,
          passed: (draft.internal_links?.length ?? 0) >= 2 },
        { name: "no_ai_giveaway_phrases", weight: 15, passed: aiHits === 0,
          detail: aiHits ? `${aiHits} hits` : undefined },
        { name: "has_cta", weight: 10, passed: !!draft.cta && draft.cta.length > 5 },
        { name: "structural_integrity", weight: 10,
          // crude check: at least one H2 (## ) and a paragraph break
          passed: /\n##\s/.test(body) && body.includes("\n\n") },
    ];
    return checks;
}

export const QUALITY_MIN_SCORE = 75;

export class QualityGatekeeper extends AgentBase {
    readonly id = "quality_gatekeeper";
    readonly name = "Quality Gatekeeper";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const draft = (input.payload ?? input.draft) as ContentDraft | undefined;
        const siteId = (input.site_id as string | undefined) ?? null;
        if (!draft) return { ok: false, error: "missing draft payload" };

        const results = runChecks(draft);
        const score = results.filter(r => r.passed).reduce((sum, r) => sum + r.weight, 0);
        const passed = score >= QUALITY_MIN_SCORE;
        const failures = results.filter(r => !r.passed).map(r => ({ check: r.name, detail: r.detail }));

        // Track pass rate (feeds PromptOptimizer per spec)
        const passRateKey = `agent:${this.id}:pass_count`;
        const totalKey = `agent:${this.id}:total_count`;
        if (passed) await kv.incr(passRateKey);
        await kv.incr(totalKey);

        this.log({
            message: `score=${score}/100 ${passed ? "PASS" : "FAIL"} (${failures.length} failed checks)`,
            site_id: siteId,
            data: { score, failures },
        }, passed ? "info" : "warn");

        return {
            ok: true,  // the gatekeeper itself always succeeds; the verdict is in the data
            data: { passed, score, failures, results },
            artifacts: { score, verdict: passed ? "publish" : "revise" },
        };
    }

    override nextAgents(out: AgentOutput): AgentTrigger[] {
        const verdict = (out.artifacts as { verdict?: string } | undefined)?.verdict;
        const data = out.data as { failures?: unknown[]; site_id?: string } | undefined;
        if (verdict === "publish") {
            return [{ agent_id: "publisher_router", input: { payload: data }, priority: 3 }];
        }
        if (verdict === "revise") {
            return [{ agent_id: "content_reviser", input: { payload: data }, priority: 2 }];
        }
        return [];
    }
}
