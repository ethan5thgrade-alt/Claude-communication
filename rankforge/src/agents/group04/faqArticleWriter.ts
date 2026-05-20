// 045 — FAQ Article Writer.
// Generates 15-25 Q&A pairs grouped by sub-topic with FAQPage schema.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface FaqPair {
    question: string;
    short_answer: string;
    elaboration: string;
    sub_topic: string;
}

export interface FaqSubTopicGroup {
    sub_topic: string;
    pairs: FaqPair[];
}

export interface FaqPageSchema {
    "@context": "https://schema.org";
    "@type": "FAQPage";
    mainEntity: {
        "@type": "Question";
        name: string;
        acceptedAnswer: { "@type": "Answer"; text: string };
    }[];
}

export type LlmFn = (prompt: string) => Promise<string>;

const QUESTION_TEMPLATES = [
    (t: string) => `What is ${t}?`,
    (t: string) => `How does ${t} work?`,
    (t: string) => `Why is ${t} important?`,
    (t: string) => `When should I use ${t}?`,
    (t: string) => `Where can I find ${t}?`,
    (t: string) => `How much does ${t} cost?`,
    (t: string) => `Is ${t} worth it?`,
    (t: string) => `What are the benefits of ${t}?`,
    (t: string) => `What are the risks of ${t}?`,
    (t: string) => `How do I get started with ${t}?`,
    (t: string) => `Who needs ${t}?`,
    (t: string) => `Can I do ${t} myself?`,
    (t: string) => `How long does ${t} take?`,
    (t: string) => `What are alternatives to ${t}?`,
    (t: string) => `Does ${t} require a professional?`,
];

const SUB_TOPIC_LABELS = ["Basics", "Cost & Pricing", "Process & How-To", "Risks & Safety", "Alternatives"];

function stubAnswer(question: string, topic: string): { short: string; long: string } {
    const short = `${topic} addresses this directly.`;
    const long = `${topic} is a common consideration for many people. ${question.replace("?", "")} depends on your context and goals. In most cases a thoughtful approach yields the best result.`;
    return { short, long };
}

export function buildFaqSchema(pairs: FaqPair[]): FaqPageSchema {
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: pairs.map(p => ({
            "@type": "Question" as const,
            name: p.question,
            acceptedAnswer: { "@type": "Answer" as const, text: `${p.short_answer} ${p.elaboration}` },
        })),
    };
}

export class FaqArticleWriter extends AgentBase {
    readonly id = "faq_article_writer";
    readonly name = "FAQ Article Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const topic = (input.topic as string | undefined) ?? (input.keyword as string | undefined);
        if (!topic || typeof topic !== "string") {
            return { ok: false, error: "topic required" };
        }
        const targetCount = Math.max(15, Math.min(25, (input.target_count as number | undefined) ?? 18));
        const llmFn = input.llm_fn as LlmFn | undefined;

        const pairs: FaqPair[] = [];
        for (let i = 0; i < targetCount; i++) {
            const tmpl = QUESTION_TEMPLATES[i % QUESTION_TEMPLATES.length];
            const question = tmpl(topic);
            const subTopic = SUB_TOPIC_LABELS[i % SUB_TOPIC_LABELS.length];
            let short: string;
            let long: string;
            if (llmFn) {
                const raw = await llmFn(`Q: ${question}\nTopic: ${topic}\nGive a 1-sentence answer then 2-4 sentence elaboration.`);
                const lines = raw.split("\n").filter(s => s.trim().length > 0);
                short = lines[0] ?? stubAnswer(question, topic).short;
                long = lines.slice(1).join(" ") || stubAnswer(question, topic).long;
            } else {
                const s = stubAnswer(question, topic);
                short = s.short;
                long = s.long;
            }
            pairs.push({ question, short_answer: short, elaboration: long, sub_topic: subTopic });
        }

        const groups = new Map<string, FaqPair[]>();
        for (const p of pairs) {
            const arr = groups.get(p.sub_topic) ?? [];
            arr.push(p);
            groups.set(p.sub_topic, arr);
        }
        const groupedBySubTopic: FaqSubTopicGroup[] = [...groups.entries()].map(([sub_topic, ps]) => ({
            sub_topic,
            pairs: ps,
        }));

        return {
            ok: true,
            data: {
                topic,
                pairs,
                pair_count: pairs.length,
                grouped_by_sub_topic: groupedBySubTopic,
                schema: buildFaqSchema(pairs),
            },
        };
    }
}
