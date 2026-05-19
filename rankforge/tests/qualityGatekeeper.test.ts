import { test } from "node:test";
import assert from "node:assert/strict";
import { QualityGatekeeper, QUALITY_MIN_SCORE } from "../src/agents/group01/qualityGatekeeper.ts";

const goodDraft = {
    title: "How to make great pour-over coffee at home",
    primary_keyword: "pour-over coffee",
    body: [
        "Pour-over coffee is a precise extraction method that yields a clean, bright cup.",
        "## What you need",
        "A gooseneck kettle, a dripper, filters, fresh beans, and a scale.",
        "## Grind size",
        "Aim for a medium-fine grind, like coarse sugar. Pour-over coffee thrives on the right grind.",
        "## Pour technique",
        "Bloom for 30 seconds with double the bean weight in water.",
        "Then pour in slow circles, keeping the bed flat.",
        "",
        Array(80).fill("Brew thoughtfully and you'll get an exceptional cup of pour-over coffee.").join(" "),
    ].join("\n\n"),
    faqs: [
        { q: "Which beans?", a: "Single-origin, medium roast." },
        { q: "Water temp?", a: "200°F." },
        { q: "Ratio?", a: "1:16 coffee to water." },
    ],
    schema: { "@type": "HowTo" },
    internal_links: [
        { href: "/best-grinders", anchor: "best grinders" },
        { href: "/coffee-bean-guide", anchor: "coffee bean guide" },
    ],
    cta: "Get our weekly brewing tips →",
};

const badDraft = {
    title: "x",
    body: "As an AI language model, I cannot.",
    word_count: 50,
};

test("QualityGatekeeper: good draft scores >= 75 and routes to publisher", async () => {
    const gate = new QualityGatekeeper();
    const out = await gate.run({ payload: goodDraft });
    const data = out.data as { passed: boolean; score: number };
    assert.equal(out.ok, true);
    assert.ok(data.score >= QUALITY_MIN_SCORE, `expected >= ${QUALITY_MIN_SCORE}, got ${data.score}`);
    assert.equal(data.passed, true);
    const triggers = gate.nextAgents(out);
    assert.equal(triggers[0]?.agent_id, "publisher_router");
});

test("QualityGatekeeper: bad draft fails and routes to reviser", async () => {
    const gate = new QualityGatekeeper();
    const out = await gate.run({ payload: badDraft });
    const data = out.data as { passed: boolean; score: number };
    assert.equal(data.passed, false);
    assert.ok(data.score < QUALITY_MIN_SCORE);
    const triggers = gate.nextAgents(out);
    assert.equal(triggers[0]?.agent_id, "content_reviser");
});

test("QualityGatekeeper: catches AI-giveaway phrases", async () => {
    const gate = new QualityGatekeeper();
    const out = await gate.run({ payload: { ...goodDraft, body: goodDraft.body + " In conclusion, delve into the world of coffee." } });
    const data = out.data as { failures: { check: string }[] };
    assert.ok(data.failures.some(f => f.check === "no_ai_giveaway_phrases"),
        `expected no_ai_giveaway_phrases to fail, got: ${JSON.stringify(data.failures)}`);
});
