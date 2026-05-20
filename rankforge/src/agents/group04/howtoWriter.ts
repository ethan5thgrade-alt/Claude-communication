// 041 — How-To Guide Writer.
// Prerequisites -> Materials -> Numbered steps -> Tips -> When to call a pro.
// Also emits HowTo JSON-LD schema derived from the step structure.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type LlmFn = (prompt: string) => Promise<string> | string;

export interface HowtoStep {
    name: string;          // <= 20 chars
    instruction: string;   // 2-5 sentences
    warning?: string;
    tip?: string;
}

export interface HowtoInput {
    keyword: string;
    prerequisites?: string[];
    materials?: string[];
    steps?: HowtoStep[];
}

function slugify(s: string): string {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
}

function titleCase(s: string): string {
    return s.replace(/\b\w/g, c => c.toUpperCase());
}

function shortName(s: string, max = 20): string {
    if (s.length <= max) return s;
    return s.slice(0, max - 1).trimEnd() + ".";
}

export function defaultHowtoTemplate(h: HowtoInput): { markdown: string; schema: Record<string, unknown> } {
    const kw = h.keyword;
    const prerequisites = h.prerequisites ?? [
        "Basic familiarity with the task",
        "A clear, well-lit workspace",
        "30-60 minutes of uninterrupted time",
    ];
    const materials = h.materials ?? [
        "Standard tool kit",
        "Safety glasses and gloves",
        "Clean cloths and a small container",
    ];
    const steps: HowtoStep[] = h.steps ?? [
        { name: "Prep area", instruction: `Clear your workspace and lay out the materials needed for ${kw}. A clean start prevents most rework.`, tip: "Cover the floor with a drop cloth." },
        { name: "Inspect", instruction: `Visually check every part before you begin ${kw}. Look for cracks, corrosion, or worn fittings.`, warning: "If you spot damage, stop and reassess." },
        { name: "Disconnect power", instruction: `Cut power or water at the source. Confirm it is off with a tester.`, warning: "Never assume — always verify." },
        { name: "Execute task", instruction: `Perform the main step of ${kw} slowly and deliberately. Keep one hand free for support.` },
        { name: "Test result", instruction: `Restore power or water and check the result. Watch for leaks, sparks, or unusual sounds for at least two minutes.` },
        { name: "Clean up", instruction: `Pack away tools and dispose of waste responsibly. Wipe down the workspace.`, tip: "Photograph the finished work for records." },
    ];

    const lines: string[] = [];
    lines.push(`# How to ${titleCase(kw)}`);
    lines.push("");
    lines.push(`**TL;DR:** Follow the ${steps.length} steps below to ${kw} safely. Allow about an hour and stop if anything looks wrong.`);
    lines.push("");
    lines.push(`## Prerequisites`);
    lines.push("");
    for (const p of prerequisites) lines.push(`- ${p}`);
    lines.push("");
    lines.push(`## Materials`);
    lines.push("");
    for (const m of materials) lines.push(`- ${m}`);
    lines.push("");
    lines.push(`## Steps`);
    lines.push("");
    steps.forEach((s, i) => {
        lines.push(`### ${i + 1}. ${shortName(s.name)}`);
        lines.push("");
        lines.push(s.instruction);
        if (s.tip) lines.push(`\n*Tip:* ${s.tip}`);
        if (s.warning) lines.push(`\n*Warning:* ${s.warning}`);
        lines.push("");
    });
    lines.push(`## Tips for Success`);
    lines.push("");
    lines.push(`- Take photos at each stage so you can reverse the process if needed.`);
    lines.push(`- Keep a notebook of what worked.`);
    lines.push("");
    lines.push(`## When to Call a Professional`);
    lines.push("");
    lines.push(`If ${kw} involves gas, structural elements, or anything you are not 100% sure about, call a licensed pro. The hourly rate is far cheaper than the cost of a mistake. [INTERNAL_LINK: contact]`);

    const schema: Record<string, unknown> = {
        "@context": "https://schema.org",
        "@type": "HowTo",
        name: `How to ${titleCase(kw)}`,
        step: steps.map((s, i) => ({
            "@type": "HowToStep",
            position: i + 1,
            name: shortName(s.name),
            text: s.instruction,
        })),
        supply: materials.map(m => ({ "@type": "HowToSupply", name: m })),
    };
    return { markdown: lines.join("\n"), schema };
}

export class HowtoWriter extends AgentBase {
    readonly id = "howto_writer";
    readonly name = "How-To Guide Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keyword = input.keyword as string | undefined;
        if (!keyword || keyword.trim().length === 0) {
            return { ok: false, error: "keyword required" };
        }
        const h: HowtoInput = {
            keyword,
            prerequisites: input.prerequisites as string[] | undefined,
            materials: input.materials as string[] | undefined,
            steps: input.steps as HowtoStep[] | undefined,
        };
        const llm = input.llm_fn as LlmFn | undefined;
        const tmpl = defaultHowtoTemplate(h);
        const content = llm ? await llm(`Write a how-to about ${keyword}`) : tmpl.markdown;
        const schemaSteps = tmpl.schema.step as { name: string; text: string; position: number }[];
        const steps = schemaSteps.map((s, i) => ({
            number: i + 1,
            name: s.name,
            instruction: s.text,
        }));
        return {
            ok: true,
            data: {
                title: `How to ${titleCase(keyword)}`,
                slug: slugify(`how-to-${keyword}`),
                markdown: content,
                schema: tmpl.schema,
                steps,
                step_count: steps.length,
            },
        };
    }
}
