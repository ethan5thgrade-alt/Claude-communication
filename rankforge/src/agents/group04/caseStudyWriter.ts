// 046 — Case Study Writer.
// Generates Challenge → Approach → Solution → Results → Key Takeaways structure.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface CaseStudySections {
    challenge: string;
    approach: string;
    solution: string;
    results: string;
    takeaways: string;
}

export interface CaseStudyMetric {
    label: string;
    before: string;
    after: string;
    change_pct: number;
}

export type LlmFn = (prompt: string) => Promise<string>;

function stubMetrics(industry: string): CaseStudyMetric[] {
    return [
        { label: `${industry} organic traffic`, before: "1,200/mo", after: "5,400/mo", change_pct: 350 },
        { label: "lead form submissions", before: "8/mo", after: "31/mo", change_pct: 287 },
        { label: "average ranking position", before: "47", after: "9", change_pct: -80 },
    ];
}

function stubSections(client: string, industry: string, problem: string): CaseStudySections {
    return {
        challenge: `${client}, a ${industry} business, faced ${problem}. Inbound leads had plateaued and the existing site was buried below page two for high-intent searches.`,
        approach: `We audited the site against ${industry} competitors, mapped a keyword cluster covering pillar and supporting topics, and prioritized fixes by traffic-recovery value.`,
        solution: `Implementation rolled out in three phases: technical SEO fixes, a refreshed content hub focused on buyer-intent queries, and a local citation cleanup pass.`,
        results: `Within 90 days, ${client} saw a measurable lift across every tracked metric, with the largest gains coming from previously-untargeted long-tail queries.`,
        takeaways: `Compounding gains came from pairing technical foundations with intent-matched content. Customize with your actual client data for maximum impact.`,
    };
}

export class CaseStudyWriter extends AgentBase {
    readonly id = "case_study_writer";
    readonly name = "Case Study Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const client = (input.client as string | undefined) ?? "Acme Co.";
        const industry = (input.industry as string | undefined) ?? "professional services";
        const problem = (input.problem as string | undefined) ?? "stagnant organic search visibility";
        const llmFn = input.llm_fn as LlmFn | undefined;

        let sections: CaseStudySections;
        if (llmFn) {
            const raw = await llmFn(`Client: ${client}\nIndustry: ${industry}\nProblem: ${problem}\nWrite five sections: challenge, approach, solution, results, takeaways.`);
            // Treat the raw stub identically — split or fall back.
            const fallback = stubSections(client, industry, problem);
            const blocks = raw.split(/\n{2,}/).map(s => s.trim()).filter(Boolean);
            sections = {
                challenge: blocks[0] ?? fallback.challenge,
                approach: blocks[1] ?? fallback.approach,
                solution: blocks[2] ?? fallback.solution,
                results: blocks[3] ?? fallback.results,
                takeaways: blocks[4] ?? fallback.takeaways,
            };
        } else {
            sections = stubSections(client, industry, problem);
        }

        const metrics = stubMetrics(industry);
        const title = `How ${client} Grew ${industry} Visibility — A Case Study`;
        const slug = title
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/(^-|-$)/g, "")
            .slice(0, 80);

        const markdown = [
            `# ${title}`,
            "",
            `## Challenge`,
            sections.challenge,
            "",
            `## Approach`,
            sections.approach,
            "",
            `## Solution`,
            sections.solution,
            "",
            `## Results`,
            sections.results,
            "",
            `## Key Takeaways`,
            sections.takeaways,
            "",
            `> Customize with your actual client data for maximum impact.`,
        ].join("\n");

        return {
            ok: true,
            data: {
                title,
                slug,
                client,
                industry,
                sections,
                metrics,
                markdown,
                note: "Customize with your actual client data for maximum impact.",
            },
        };
    }
}
