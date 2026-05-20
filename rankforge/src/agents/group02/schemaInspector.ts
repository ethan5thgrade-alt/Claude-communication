// 016 — Schema Inspector & Validator.
// Parses JSON-LD, validates against required properties per common type.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";

// Subset of schema.org required properties. Expand as needed.
const REQUIRED_PROPS: Record<string, string[]> = {
    Article: ["headline", "author", "datePublished"],
    BlogPosting: ["headline", "author", "datePublished"],
    NewsArticle: ["headline", "author", "datePublished"],
    Product: ["name", "image"],
    Recipe: ["name", "recipeIngredient", "recipeInstructions"],
    HowTo: ["name", "step"],
    FAQPage: ["mainEntity"],
    Organization: ["name"],
    LocalBusiness: ["name", "address"],
    BreadcrumbList: ["itemListElement"],
    VideoObject: ["name", "thumbnailUrl", "uploadDate"],
    Event: ["name", "startDate", "location"],
};

export interface SchemaValidation {
    page_url: string;
    schemas_found: { type: string; valid: boolean; missing_props: string[] }[];
    types_present: string[];
    invalid_count: number;
}

export function validatePageSchemas(page: ParsedPage): SchemaValidation {
    const schemasFound: { type: string; valid: boolean; missing_props: string[] }[] = [];
    const typesPresent = new Set<string>();
    for (const block of page.schemas) {
        if (block.format !== "json-ld") {
            const t = block.type ?? "Unknown";
            typesPresent.add(t);
            schemasFound.push({ type: t, valid: true, missing_props: [] });
            continue;
        }
        const data = block.data as Record<string, unknown> | undefined;
        if (!data) {
            schemasFound.push({ type: "(unparseable)", valid: false, missing_props: ["json_parse_error"] });
            continue;
        }
        const type = (data["@type"] as string | undefined) ?? "Unknown";
        typesPresent.add(type);
        const required = REQUIRED_PROPS[type] ?? [];
        const missing = required.filter(prop => !(prop in data));
        schemasFound.push({ type, valid: missing.length === 0, missing_props: missing });
    }
    return {
        page_url: page.url,
        schemas_found: schemasFound,
        types_present: Array.from(typesPresent),
        invalid_count: schemasFound.filter(s => !s.valid).length,
    };
}

export class SchemaInspector extends AgentBase {
    readonly id = "schema_inspector";
    readonly name = "Schema Inspector & Validator";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const parsed = (input.parsed as ParsedPage[] | undefined) ?? [];
        if (parsed.length === 0) return { ok: false, error: "no parsed pages" };
        const validations = parsed.map(p => validatePageSchemas(p));
        const inventory: Record<string, number> = {};
        for (const v of validations) for (const t of v.types_present) inventory[t] = (inventory[t] ?? 0) + 1;
        const totalInvalid = validations.reduce((s, v) => s + v.invalid_count, 0);
        return {
            ok: true,
            data: { validations, inventory, total_invalid: totalInvalid },
        };
    }
}
