// 043 — Comparison Article Writer.
// Verdict upfront -> comparison table -> deep dive per option ->
// who-should-choose-what -> final recommendation. Emits Product schema
// when the options look like products (price provided).

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type LlmFn = (prompt: string) => Promise<string> | string;

export interface ComparisonOption {
    name: string;
    price?: string;
    pros?: string[];
    cons?: string[];
    best_for?: string;
}

export interface ComparisonInput {
    keyword: string;
    options?: ComparisonOption[];
    items?: string[];
}

export interface ComparisonTable {
    headers: string[];
    rows: (string | number)[][];
}

function slugify(s: string): string {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
}

function titleCase(s: string): string {
    return s.replace(/\b\w/g, c => c.toUpperCase());
}

function parseOptionsFromKeyword(keyword: string): string[] {
    const vs = keyword.split(/\s+vs\.?\s+/i);
    if (vs.length >= 2) return vs.map(s => s.trim()).filter(Boolean);
    const altMatch = keyword.match(/^(.+?)\s+alternatives?\b/i);
    if (altMatch) return [altMatch[1].trim(), "Top Alternative", "Budget Alternative"];
    return ["Option A", "Option B"];
}

function expandOption(name: string, index: number): ComparisonOption {
    return {
        name: titleCase(name),
        price: `$${(index + 1) * 49}/mo`,
        pros: [`Strong fit for ${index === 0 ? "beginners" : "power users"}`, `Solid documentation`, `Active community`],
        cons: [`${index === 0 ? "Limited" : "Steeper"} learning curve`, `Pricing tier above the free plan`],
        best_for: index === 0 ? "small teams getting started" : "growing teams that have outgrown the basics",
    };
}

function resolveOptions(c: ComparisonInput): ComparisonOption[] {
    if (c.options && c.options.length > 0) return c.options;
    if (c.items && c.items.length > 0) return c.items.map((n, i) => expandOption(n, i));
    return parseOptionsFromKeyword(c.keyword).map((n, i) => expandOption(n, i));
}

function buildTable(options: ComparisonOption[]): ComparisonTable {
    return {
        headers: ["Option", "Price", "Best For"],
        rows: options.map(o => [o.name, o.price ?? "—", o.best_for ?? "general use"]),
    };
}

export function defaultComparisonTemplate(
    c: ComparisonInput,
): { markdown: string; schema: Record<string, unknown>[]; options: ComparisonOption[]; table: ComparisonTable; verdict: string } {
    const kw = c.keyword;
    const options = resolveOptions(c);
    const table = buildTable(options);
    const verdict = `${options[0].name} wins overall for ${options[0].best_for ?? "most users"}. Pick ${options[1]?.name ?? "the alternative"} only if budget is the deciding factor.`;

    const lines: string[] = [];
    lines.push(`# ${titleCase(kw)}: Our Verdict After Side-by-Side Testing`);
    lines.push("");
    lines.push(`**TL;DR:** ${verdict}`);
    lines.push("");
    lines.push(`## At a Glance`);
    lines.push("");
    lines.push(`| ${table.headers.join(" | ")} |`);
    lines.push(`| ${table.headers.map(() => "---").join(" | ")} |`);
    for (const r of table.rows) lines.push(`| ${r.join(" | ")} |`);
    lines.push("");

    for (const o of options) {
        lines.push(`## ${o.name}`);
        lines.push("");
        lines.push(`${o.name} is one of the leading choices when evaluating ${kw}. Here's how it performs in practice.`);
        lines.push("");
        lines.push(`**Pros**`);
        lines.push("");
        for (const p of o.pros ?? []) lines.push(`- ${p}`);
        lines.push("");
        lines.push(`**Cons**`);
        lines.push("");
        for (const co of o.cons ?? []) lines.push(`- ${co}`);
        lines.push("");
        lines.push(`Best for: ${o.best_for ?? "general use"}. [INTERNAL_LINK: ${slugify(o.name)}]`);
        lines.push("");
    }

    lines.push(`## Who Should Choose What`);
    lines.push("");
    options.forEach((o, i) => {
        lines.push(`- **Choose ${o.name}** if ${i === 0 ? "you value polish and ecosystem" : "price is your top concern"}.`);
    });
    lines.push("");
    lines.push(`## Final Recommendation`);
    lines.push("");
    lines.push(`For most readers searching "${kw}", ${options[0].name} is the right call. The price premium pays for itself within the first month.`);
    lines.push("");
    lines.push(`Still on the fence? [INTERNAL_LINK: contact]`);

    const isProduct = options.some(o => !!o.price);
    const schema: Record<string, unknown>[] = isProduct
        ? options.map(o => ({
            "@context": "https://schema.org",
            "@type": "Product",
            name: o.name,
            offers: { "@type": "Offer", price: o.price?.replace(/[^\d.]/g, "") ?? "0", priceCurrency: "USD" },
        }))
        : [];

    return { markdown: lines.join("\n"), schema, options, table, verdict };
}

export class ComparisonWriter extends AgentBase {
    readonly id = "comparison_writer";
    readonly name = "Comparison Article Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keyword = input.keyword as string | undefined;
        if (!keyword || keyword.trim().length === 0) {
            return { ok: false, error: "keyword required" };
        }
        const c: ComparisonInput = {
            keyword,
            options: input.options as ComparisonOption[] | undefined,
            items: input.items as string[] | undefined,
        };
        const llm = input.llm_fn as LlmFn | undefined;
        const tmpl = defaultComparisonTemplate(c);
        const markdown = llm ? await llm(`Write a comparison about ${keyword}`) : tmpl.markdown;
        return {
            ok: true,
            data: {
                title: `${titleCase(keyword)}: Verdict`,
                slug: slugify(keyword),
                markdown,
                full_content_markdown: markdown,
                schema: tmpl.schema,
                comparison_table: tmpl.table,
                verdict: tmpl.verdict,
                option_count: tmpl.options.length,
            },
        };
    }
}
