import { test } from "node:test";
import assert from "node:assert/strict";

import { ContentPlanner } from "../src/agents/group04/contentPlanner.ts";
import { BlogWriter } from "../src/agents/group04/blogWriter.ts";
import { HowtoWriter } from "../src/agents/group04/howtoWriter.ts";
import { ListicleWriter } from "../src/agents/group04/listicleWriter.ts";
import { ComparisonWriter } from "../src/agents/group04/comparisonWriter.ts";
import { LocalPageWriter } from "../src/agents/group04/localPageWriter.ts";
import { FaqArticleWriter } from "../src/agents/group04/faqArticleWriter.ts";
import { CaseStudyWriter } from "../src/agents/group04/caseStudyWriter.ts";
import { PressReleaseWriter } from "../src/agents/group04/pressReleaseWriter.ts";
import { EmailWriter } from "../src/agents/group04/emailWriter.ts";
import { VideoScriptWriter } from "../src/agents/group04/videoScriptWriter.ts";

test("content_planner sequences pillar before its supporting briefs", async () => {
    const agent = new ContentPlanner();
    const out = await agent.run({
        clusters: [
            {
                theme: "espresso",
                pillar: "best espresso machine",
                supporting: ["espresso machine reviews", "cheap espresso machine"],
                total_volume: 8000,
                priority: 80,
            },
        ],
        monthly_cap: 10,
    });
    assert.equal(out.ok, true);
    const data = out.data as { briefs: { role: string; sequence: number }[] };
    assert.equal(data.briefs[0].role, "pillar");
    assert.ok(data.briefs.slice(1).every(b => b.role === "supporting"));
});

test("blog_writer output contains title, meta_title, meta_description, slug, markdown body", async () => {
    const agent = new BlogWriter();
    const out = await agent.run({ keyword: "what is direct mail" });
    assert.equal(out.ok, true);
    const data = out.data as {
        title: string;
        meta_title: string;
        meta_description: string;
        slug: string;
        markdown: string;
    };
    assert.ok(data.title.length > 0);
    assert.ok(data.meta_title.length > 0);
    assert.ok(data.meta_description.length > 0);
    assert.ok(/^[a-z0-9-]+$/.test(data.slug));
    assert.ok(data.markdown.includes("#"));
});

test("howto_writer produces HowTo schema with numbered steps", async () => {
    const agent = new HowtoWriter();
    const out = await agent.run({ keyword: "how to unclog a sink" });
    assert.equal(out.ok, true);
    const data = out.data as {
        schema: { "@type": string; step: { "@type": string; position: number; name: string }[] };
        step_count: number;
    };
    assert.equal(data.schema["@type"], "HowTo");
    assert.ok(data.schema.step.length >= 3);
    assert.equal(data.schema.step[0]["@type"], "HowToStep");
    assert.equal(data.schema.step[0].position, 1);
    assert.ok(data.step_count >= 3);
});

test("listicle_writer respects N-item count from input", async () => {
    const agent = new ListicleWriter();
    const out = await agent.run({ keyword: "best espresso machines", item_count: 7 });
    assert.equal(out.ok, true);
    const data = out.data as { item_count: number };
    assert.equal(data.item_count, 7);
});

test("comparison_writer outputs comparison table + verdict in markdown", async () => {
    const agent = new ComparisonWriter();
    const out = await agent.run({ keyword: "breville vs delonghi" });
    assert.equal(out.ok, true);
    const data = out.data as {
        markdown: string;
        option_count: number;
        schema: unknown[];
    };
    // Markdown should include both a table and a verdict section
    assert.ok(data.markdown.includes("|"), "expected markdown table");
    assert.ok(/verdict|recommendation/i.test(data.markdown));
    assert.ok(data.option_count >= 2);
});

test("local_page_writer requires city; LocalBusiness schema present when provided", async () => {
    const agent = new LocalPageWriter();
    const bad = await agent.run({ service: "plumbing" });
    assert.equal(bad.ok, false);
    const good = await agent.run({
        service: "plumbing",
        city: "Austin",
    });
    assert.equal(good.ok, true);
    const data = good.data as { schema: { "@type": string } };
    assert.equal(data.schema["@type"], "LocalBusiness");
});

test("faq_article_writer produces 15+ Q&A pairs + FAQPage schema", async () => {
    const agent = new FaqArticleWriter();
    const out = await agent.run({ topic: "solar panel installation" });
    assert.equal(out.ok, true);
    const data = out.data as {
        pairs: { question: string; short_answer: string }[];
        schema: { "@type": string; mainEntity: { "@type": string }[] };
        grouped_by_sub_topic: { sub_topic: string; pairs: unknown[] }[];
    };
    assert.ok(data.pairs.length >= 15, `got ${data.pairs.length} pairs`);
    assert.ok(data.pairs.length <= 25);
    assert.equal(data.schema["@type"], "FAQPage");
    assert.equal(data.schema.mainEntity[0]["@type"], "Question");
    assert.ok(data.grouped_by_sub_topic.length >= 2);
    assert.ok(data.pairs.every(p => p.question.endsWith("?")));
});

test("faq_article_writer rejects missing topic", async () => {
    const agent = new FaqArticleWriter();
    const out = await agent.run({});
    assert.equal(out.ok, false);
});

test("case_study_writer has all 5 sections", async () => {
    const agent = new CaseStudyWriter();
    const out = await agent.run({
        client: "Northgate HVAC",
        industry: "HVAC",
        problem: "stagnant lead volume",
    });
    assert.equal(out.ok, true);
    const data = out.data as {
        sections: {
            challenge: string; approach: string; solution: string; results: string; takeaways: string;
        };
        markdown: string;
    };
    assert.ok(data.sections.challenge.length > 0);
    assert.ok(data.sections.approach.length > 0);
    assert.ok(data.sections.solution.length > 0);
    assert.ok(data.sections.results.length > 0);
    assert.ok(data.sections.takeaways.length > 0);
    for (const h of ["Challenge", "Approach", "Solution", "Results", "Key Takeaways"]) {
        assert.ok(data.markdown.includes(`## ${h}`), `missing section header ${h}`);
    }
});

test("press_release_writer has dateline + quote + 5Ws", async () => {
    const agent = new PressReleaseWriter();
    const bad = await agent.run({});
    assert.equal(bad.ok, false);
    const out = await agent.run({
        business: "Joe's Auto Repair",
        trigger: "new_service",
        city: "Boise",
        state: "ID",
        release_date: "2026-03-15T00:00:00Z",
        quote: "We're proud to offer this to the community.",
    });
    assert.equal(out.ok, true);
    const data = out.data as {
        dateline: string;
        five_ws: { who: string; what: string; when: string; where: string; why: string };
        body: string;
        full_text: string;
        distribution_list: string[];
    };
    assert.ok(data.dateline.includes("BOISE"));
    assert.ok(data.dateline.includes("2026"));
    assert.ok(data.body.includes("\""), "expected a quote in body");
    assert.ok(data.five_ws.who.length > 0);
    assert.ok(data.five_ws.what.length > 0);
    assert.ok(data.distribution_list.length >= 3);
    assert.ok(data.full_text.includes("FOR IMMEDIATE RELEASE"));
});

test("email_writer outputs 5+ emails each with 3 subject variants", async () => {
    const agent = new EmailWriter();
    const out = await agent.run({
        topic: "lead generation for plumbers",
        campaign_type: "nurture",
        sequence_length: 6,
    });
    assert.equal(out.ok, true);
    const data = out.data as {
        emails: {
            subject_variants: string[];
            preview_text: string;
            body: string;
            sequence_number: number;
        }[];
    };
    assert.ok(data.emails.length >= 5);
    assert.ok(data.emails.length <= 7);
    for (const email of data.emails) {
        assert.equal(email.subject_variants.length, 3);
        assert.ok(email.preview_text.length > 0);
        assert.ok(email.body.length > 0);
    }
    assert.equal(data.emails[0].sequence_number, 1);
});

test("email_writer rejects missing topic", async () => {
    const agent = new EmailWriter();
    const out = await agent.run({});
    assert.equal(out.ok, false);
});

test("video_script_writer respects length tier and outputs YouTube tags", async () => {
    const agent = new VideoScriptWriter();
    const shortOut = await agent.run({ topic: "fix a leaky faucet", length: "short" });
    const longOut = await agent.run({ topic: "fix a leaky faucet", length: "long" });
    assert.equal(shortOut.ok, true);
    assert.equal(longOut.ok, true);
    const s = shortOut.data as { duration_sec: number; segments: unknown[]; youtube: { tags: string[] } };
    const l = longOut.data as { duration_sec: number; segments: unknown[]; youtube: { tags: string[]; chapters: unknown[] } };
    assert.ok(s.duration_sec <= 60);
    assert.ok(l.duration_sec >= 600);
    assert.ok(l.segments.length > s.segments.length);
    assert.ok(s.youtube.tags.length >= 5);
    assert.ok(l.youtube.chapters.length >= 5);
});

test("video_script_writer produces VideoObject schema and validates length", async () => {
    const agent = new VideoScriptWriter();
    const bad = await agent.run({ topic: "x", length: "epic" });
    assert.equal(bad.ok, false);
    const out = await agent.run({ topic: "espresso basics", length: "medium" });
    assert.equal(out.ok, true);
    const data = out.data as { schema: { "@type": string; duration: string }; full_script: string };
    assert.equal(data.schema["@type"], "VideoObject");
    assert.ok(data.schema.duration.startsWith("PT"));
    assert.ok(data.full_script.includes("VO:"));
    assert.ok(data.full_script.includes("B-ROLL:"));
});

test("video_script_writer applies llm_fn override to voiceovers", async () => {
    const agent = new VideoScriptWriter();
    const out = await agent.run({
        topic: "test topic",
        length: "short",
        llm_fn: async (_prompt: string) => "OVERRIDDEN",
    });
    assert.equal(out.ok, true);
    const data = out.data as { segments: { voiceover: string }[] };
    assert.ok(data.segments.every(s => s.voiceover === "OVERRIDDEN"));
});
