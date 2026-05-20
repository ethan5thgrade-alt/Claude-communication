// 036 — Voice Search Optimizer.
// Generates conversational, voice-search-optimized variants of a keyword.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface VoiceVariants {
    keyword: string;
    variants: string[];
    near_me?: string;
    short_answer_target: string;
}

const ASSISTANT_PREFIXES = ["hey google,", "ok google,", "hey siri,", "alexa,"];

function startsWithQuestionWord(s: string): boolean {
    return /^(how|what|why|when|where|who|which|can|is|are|do|does|should)\b/i.test(s);
}

export function toVoiceVariants(keyword: string, opts: { local?: boolean } = {}): VoiceVariants {
    const kw = keyword.trim();
    const lower = kw.toLowerCase();
    const variants: string[] = [];

    // 1. Assistant prefix variant
    const isQ = startsWithQuestionWord(lower);
    const natural = isQ ? lower : `how do i ${lower}`;
    variants.push(`${ASSISTANT_PREFIXES[0]} ${natural}`);

    // 2. Natural-language question variant
    if (isQ) {
        variants.push(lower.endsWith("?") ? lower : `${lower}?`);
    } else {
        variants.push(`what is the best ${lower}?`);
    }

    // 3. Conversational "tell me" variant
    variants.push(`tell me about ${lower}`);

    // 4. Near-me variant (always included for local potential)
    const nearMe = `${lower} near me`;
    variants.push(nearMe);

    // 5. "I need" / "find me" variant
    variants.push(`find me ${lower}`);

    // Short-answer target: 40-60 char direct-answer prompt
    const shortAnswer = isQ
        ? `Quick answer: ${lower.replace(/\?$/, "")}.`
        : `${kw} is best understood as`;

    return {
        keyword: kw,
        variants: Array.from(new Set(variants)),
        near_me: opts.local !== false ? nearMe : undefined,
        short_answer_target: shortAnswer,
    };
}

export class VoiceOptimizer extends AgentBase {
    readonly id = "voice_optimizer";
    readonly name = "Voice Search Optimizer";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = input.keywords as string[] | undefined;
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords array required" };
        }
        const local = input.local !== false;
        const results = keywords.map(k => toVoiceVariants(k, { local }));
        const totalVariants = results.reduce((s, r) => s + r.variants.length, 0);
        return {
            ok: true,
            data: {
                results,
                count: results.length,
                total_variants: totalVariants,
            },
        };
    }
}
