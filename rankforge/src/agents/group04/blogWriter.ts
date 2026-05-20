// 040 — Master Blog Post Writer.
// Produces an 800-3000 word SEO-optimized markdown post.
// No live LLM call — accepts optional `input.llm_fn`; otherwise emits a
// deterministic template with the shape spec requires:
//   H1 -> TL;DR -> intro -> H2 sections -> 8-Q FAQ -> CTA.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type LlmFn = (prompt: string) => Promise<string> | string;

export interface BlogInput {
    keyword: string;
    audience?: string;
    niche?: string;
    target_words?: number;
    sections?: string[];
}

function slugify(s: string): string {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
}

function titleCase(s: string): string {
    return s.replace(/\b\w/g, c => c.toUpperCase());
}

export function defaultBlogTemplate(b: BlogInput): string {
    const kw = b.keyword;
    const audience = b.audience ?? "homeowners";
    const niche = b.niche ?? "home services";
    const sections = b.sections ?? [
        `Why ${titleCase(kw)} Matters`,
        `How ${titleCase(kw)} Works`,
        `Common Mistakes to Avoid`,
        `When to Call a Professional`,
        `Cost Breakdown`,
    ];
    const lines: string[] = [];
    lines.push(`# ${titleCase(kw)}: A Practical Guide for ${titleCase(audience)}`);
    lines.push("");
    lines.push(`**TL;DR:** ${titleCase(kw)} is a core part of ${niche}. This guide covers what it is, how to do it right, what it costs, and when to hire help. Read the FAQ at the bottom for quick answers.`);
    lines.push("");
    lines.push(`${titleCase(kw)} is one of the most searched topics in ${niche}, and the short answer is: most ${audience} can handle the basics, but the details matter. Below, we break down the full picture in plain English.`);
    lines.push("");
    for (const s of sections) {
        lines.push(`## ${s}`);
        lines.push("");
        lines.push(`This section explains ${s.toLowerCase()} as it relates to ${kw}. Key points to remember: keep your work organized, follow local codes, and document each step. [INTERNAL_LINK: ${slugify(s)}]`);
        lines.push("");
        lines.push(`[IMAGE: ${s} illustration]`);
        lines.push("");
    }
    lines.push(`## Frequently Asked Questions`);
    lines.push("");
    const faqs: { q: string; a: string }[] = [
        { q: `What is ${kw}?`, a: `${titleCase(kw)} is a process within ${niche} used by ${audience} every day.` },
        { q: `How much does ${kw} cost?`, a: `Typical cost ranges from $100 to $1,500 depending on scope.` },
        { q: `Is ${kw} a DIY job?`, a: `Basic versions are DIY-friendly; complex jobs need a licensed pro.` },
        { q: `How long does ${kw} take?`, a: `Most projects take 1-3 days for a typical ${audience.replace(/s$/, "")}.` },
        { q: `What tools do I need for ${kw}?`, a: `Standard hand tools plus one or two specialty items.` },
        { q: `Is ${kw} dangerous?`, a: `Risks are low if you follow safety steps; high if you skip them.` },
        { q: `Do I need a permit for ${kw}?`, a: `It depends on your municipality; check local codes first.` },
        { q: `When should I hire a pro for ${kw}?`, a: `When the work touches structure, gas, or electrical at scale.` },
    ];
    for (const f of faqs) {
        lines.push(`**Q: ${f.q}**`);
        lines.push("");
        lines.push(f.a);
        lines.push("");
    }
    lines.push(`## Ready to Get Started?`);
    lines.push("");
    lines.push(`If you want help with ${kw}, get a free quote today. [INTERNAL_LINK: contact]`);
    return lines.join("\n");
}

function wordCount(s: string): number {
    return s.split(/\s+/).filter(Boolean).length;
}

export class BlogWriter extends AgentBase {
    readonly id = "blog_writer";
    readonly name = "Master Blog Post Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keyword = input.keyword as string | undefined;
        if (!keyword || keyword.trim().length === 0) {
            return { ok: false, error: "keyword required" };
        }
        const b: BlogInput = {
            keyword,
            audience: input.audience as string | undefined,
            niche: input.niche as string | undefined,
            target_words: input.target_words as number | undefined,
            sections: input.sections as string[] | undefined,
        };
        const llm = input.llm_fn as LlmFn | undefined;
        const markdown = llm ? await llm(`Write a blog post about ${keyword}`) : defaultBlogTemplate(b);
        const title = `${titleCase(keyword)}: A Practical Guide`;
        return {
            ok: true,
            data: {
                title,
                meta_title: `${title} | ${titleCase(b.niche ?? "Guide")}`,
                meta_description: `Everything you need to know about ${keyword}: cost, DIY tips, when to call a pro, and answers to the 8 most-asked questions.`.slice(0, 160),
                slug: slugify(keyword),
                markdown,
                full_content_markdown: markdown,
                word_count: wordCount(markdown),
            },
        };
    }
}
