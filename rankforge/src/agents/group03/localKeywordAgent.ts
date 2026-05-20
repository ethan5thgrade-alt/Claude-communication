// 028 — Local SEO Keyword Agent.
// If location detected, generates geo-targeted keywords across standard
// templates + nearby cities within 30mi radius.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface LocalContext {
    city: string;
    state?: string;
    neighborhood?: string;
    zip?: string;
    nearby_cities?: { name: string; distance_mi: number }[];
}

export type LocalKeywordType =
    | "in_city"
    | "near_me"
    | "city_state"
    | "best_city"
    | "neighborhood"
    | "zip_area"
    | "emergency"
    | "open_now"
    | "price"
    | "nearby_city";

export interface LocalKeyword {
    keyword: string;
    service: string;
    location: string;
    type: LocalKeywordType;
}

const NEARBY_RADIUS_MI = 30;

function clean(s: string | undefined): string {
    return (s ?? "").toLowerCase().trim();
}

function buildForLocation(service: string, loc: LocalContext): LocalKeyword[] {
    const s = clean(service);
    const city = clean(loc.city);
    if (!s || !city) return [];
    const out: LocalKeyword[] = [];
    out.push({ keyword: `${s} in ${city}`, service, location: city, type: "in_city" });
    out.push({ keyword: `${s} near me`, service, location: city, type: "near_me" });
    if (loc.state) {
        out.push({ keyword: `${s} ${city} ${clean(loc.state)}`, service, location: city, type: "city_state" });
    }
    out.push({ keyword: `best ${s} ${city}`, service, location: city, type: "best_city" });
    if (loc.neighborhood) {
        out.push({ keyword: `${s} ${clean(loc.neighborhood)}`, service, location: clean(loc.neighborhood), type: "neighborhood" });
    }
    if (loc.zip) {
        out.push({ keyword: `${s} ${loc.zip}`, service, location: loc.zip, type: "zip_area" });
    }
    out.push({ keyword: `emergency ${s} ${city}`, service, location: city, type: "emergency" });
    out.push({ keyword: `${s} ${city} open now`, service, location: city, type: "open_now" });
    out.push({ keyword: `${s} ${city} cost`, service, location: city, type: "price" });
    out.push({ keyword: `${s} ${city} price`, service, location: city, type: "price" });
    out.push({ keyword: `${s} ${city} rates`, service, location: city, type: "price" });
    return out;
}

export function generateLocalKeywords(services: string[], loc: LocalContext): LocalKeyword[] {
    const out: LocalKeyword[] = [];
    const seen = new Set<string>();
    for (const service of services) {
        for (const k of buildForLocation(service, loc)) {
            const key = k.keyword;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push(k);
        }
        const nearby = (loc.nearby_cities ?? []).filter(c => c.distance_mi <= NEARBY_RADIUS_MI);
        for (const nc of nearby) {
            const key = `${clean(service)} ${clean(nc.name)}`;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({ keyword: key, service, location: clean(nc.name), type: "nearby_city" });
        }
    }
    return out;
}

export class LocalKeywordAgent extends AgentBase {
    readonly id = "local_keyword_agent";
    readonly name = "Local SEO Keyword Agent";
    readonly group = 3;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const services = (input.services as string[] | undefined)
            ?? (input.seeds as string[] | undefined)
            ?? (input.keywords as string[] | undefined)
            ?? [];
        const location = input.location as LocalContext | undefined;
        if (!location || !location.city) {
            return { ok: true, data: { local_keywords: [], count: 0, skipped: true, reason: "no_location" } };
        }
        if (!Array.isArray(services) || services.length === 0) {
            return { ok: false, error: "services required" };
        }
        const keywords = generateLocalKeywords(services, location);
        return { ok: true, data: { local_keywords: keywords, count: keywords.length, skipped: false } };
    }
}
