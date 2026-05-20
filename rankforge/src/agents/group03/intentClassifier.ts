// 030 — Search Intent Classifier.
// Assigns primary intent + content type + schema for each keyword.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type Intent =
    | "informational"
    | "commercial"
    | "transactional"
    | "navigational"
    | "local"
    | "question";

export type ContentType =
    | "blog_post"
    | "how_to_guide"
    | "comparison"
    | "review"
    | "service_page"
    | "product_page"
    | "local_landing"
    | "faq_article"
    | "skip";

export type SchemaType =
    | "Article"
    | "HowTo"
    | "FAQPage"
    | "Product"
    | "Service"
    | "LocalBusiness"
    | "Review"
    | "none";

export interface ClassifiedKeyword {
    keyword: string;
    intent: Intent;
    content_type_recommendation: ContentType;
    schema_recommendation: SchemaType;
    confidence: number;
}

const QUESTION_STARTERS = ["how", "what", "why", "when", "where", "who", "which", "can", "is", "are", "does", "do"];
const TRANSACTIONAL = ["buy", "order", "hire", "book", "subscribe", "pricing", "price", "cost", "rates", "quote", "discount", "deal", "coupon"];
const COMMERCIAL = ["best", "top", "review", "reviews", "vs", "versus", "compare", "comparison", "alternative", "alternatives"];
const NAVIGATIONAL = ["login", "log in", "sign in", "sign up", "dashboard", "account", "contact"];
const LOCAL = ["near me", "in ", " near ", " open now"];

function hasAny(kw: string, list: string[]): boolean {
    return list.some(t => kw.includes(t));
}

export function classifyKeyword(keyword: string): ClassifiedKeyword {
    const kw = keyword.toLowerCase().trim();
    const first = kw.split(/\s+/)[0];
    let intent: Intent = "informational";
    let confidence = 0.6;
    if (hasAny(kw, NAVIGATIONAL)) {
        intent = "navigational";
        confidence = 0.85;
    } else if (hasAny(kw, LOCAL) || / \d{5}$/.test(kw)) {
        intent = "local";
        confidence = 0.8;
    } else if (QUESTION_STARTERS.includes(first)) {
        intent = "question";
        confidence = 0.9;
    } else if (hasAny(kw, TRANSACTIONAL)) {
        intent = "transactional";
        confidence = 0.85;
    } else if (hasAny(kw, COMMERCIAL)) {
        intent = "commercial";
        confidence = 0.8;
    }

    let contentType: ContentType;
    let schema: SchemaType;
    switch (intent) {
        case "navigational":
            contentType = "skip";
            schema = "none";
            break;
        case "local":
            contentType = "local_landing";
            schema = "LocalBusiness";
            break;
        case "question":
            contentType = "faq_article";
            schema = "FAQPage";
            break;
        case "transactional":
            contentType = kw.includes("product") ? "product_page" : "service_page";
            schema = contentType === "product_page" ? "Product" : "Service";
            break;
        case "commercial":
            contentType = kw.includes("review") ? "review" : "comparison";
            schema = contentType === "review" ? "Review" : "Article";
            break;
        case "informational":
        default:
            contentType = kw.startsWith("how to") ? "how_to_guide" : "blog_post";
            schema = contentType === "how_to_guide" ? "HowTo" : "Article";
            break;
    }
    return { keyword: kw, intent, content_type_recommendation: contentType, schema_recommendation: schema, confidence };
}

export class IntentClassifier extends AgentBase {
    readonly id = "intent_classifier";
    readonly name = "Search Intent Classifier";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const keywords = (input.keywords as string[] | undefined)
            ?? (input.seeds as string[] | undefined)
            ?? [];
        if (!Array.isArray(keywords) || keywords.length === 0) {
            return { ok: false, error: "keywords required" };
        }
        const classified = keywords.map(k => classifyKeyword(k));
        const byIntent: Record<Intent, number> = {
            informational: 0, commercial: 0, transactional: 0,
            navigational: 0, local: 0, question: 0,
        };
        for (const c of classified) byIntent[c.intent]++;
        return { ok: true, data: { classified, count: classified.length, by_intent: byIntent } };
    }
}
