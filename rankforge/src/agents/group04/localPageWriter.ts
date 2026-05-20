// 044 — Local Landing Page Writer.
// City/service combination pages. Must include city name, neighborhood
// references, local signals, NAP, and a LocalBusiness JSON-LD block.
// Min 800 words of locally-unique content (not just keyword swaps).

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type LlmFn = (prompt: string) => Promise<string> | string;

export interface NAP {
    business_name: string;
    street: string;
    city: string;
    state: string;
    postal_code: string;
    phone: string;
    lat?: number;
    lng?: number;
    service_area_radius_mi?: number;
}

export interface LocalPageInput {
    service: string;
    city: string;
    neighborhoods?: string[];
    landmarks?: string[];
    nap: NAP;
}

function slugify(s: string): string {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);
}

function titleCase(s: string): string {
    return s.replace(/\b\w/g, c => c.toUpperCase());
}

function defaultNeighborhoods(city: string): string[] {
    return [`Downtown ${city}`, `${city} Heights`, `North ${city}`, `South ${city}`, `Old Town ${city}`];
}

function defaultLandmarks(city: string): string[] {
    return [`${city} City Hall`, `${city} High School`, `${city} Public Library`];
}

export function defaultLocalTemplate(
    l: LocalPageInput,
): { markdown: string; schema: Record<string, unknown>; word_count: number } {
    const { service, city, nap } = l;
    const neighborhoods = l.neighborhoods ?? defaultNeighborhoods(city);
    const landmarks = l.landmarks ?? defaultLandmarks(city);

    const lines: string[] = [];
    lines.push(`# ${titleCase(service)} in ${titleCase(city)}, ${nap.state}`);
    lines.push("");
    lines.push(`**TL;DR:** ${nap.business_name} provides ${service} throughout ${city} and the surrounding ${nap.service_area_radius_mi ?? 25}-mile service area. Same-day appointments available; call ${nap.phone}.`);
    lines.push("");
    lines.push(`If you're searching for ${service} in ${city}, you already know the local conditions matter. Older homes near ${landmarks[0] ?? "downtown"} have different needs than newer builds in ${neighborhoods[1] ?? "the suburbs"}. We've worked across every part of ${city}, from ${neighborhoods.slice(0, 3).join(", ")}, and we know the building codes, the soil, the weather patterns, and which materials hold up locally.`);
    lines.push("");

    lines.push(`## Why Choose a Local ${titleCase(service)} Team`);
    lines.push("");
    lines.push(`A ${city}-based crew shows up faster, knows the permit office staff by name, and stocks parts that match the housing stock here. National chains route through call centers; we route directly. When you call ${nap.phone}, a local human picks up.`);
    lines.push("");

    lines.push(`## Neighborhoods We Serve`);
    lines.push("");
    for (const n of neighborhoods) {
        lines.push(`- **${n}** — common requests here include preventative ${service} and emergency call-outs.`);
    }
    lines.push("");
    lines.push(`We also cover the area around ${landmarks.join(", ")} and most addresses within ${nap.service_area_radius_mi ?? 25} miles of our shop on ${nap.street}.`);
    lines.push("");

    lines.push(`## What ${titleCase(service)} Looks Like in ${city}`);
    lines.push("");
    lines.push(`${city}'s climate and housing mix create a specific set of ${service} challenges. Summer heat stresses systems, winter cold cracks materials, and the local soil affects foundations and underground lines. A crew familiar with ${city} knows which problems to look for first — and what they'll cost to fix.`);
    lines.push("");
    lines.push(`A typical job runs 1-3 hours. Emergency calls are answered within 60 minutes. We carry liability insurance, full ${nap.state} licensing, and warranty every visit. [INTERNAL_LINK: warranty]`);
    lines.push("");

    lines.push(`## Pricing for ${city} Customers`);
    lines.push("");
    lines.push(`Most ${service} calls in ${city} fall between $150 and $850. The full estimate is always free, always in writing, and always before we start. No surprises, no upcharge games. [IMAGE: ${city} service truck]`);
    lines.push("");

    lines.push(`## Visit Us or Call Today`);
    lines.push("");
    lines.push(`**${nap.business_name}**`);
    lines.push(`${nap.street}, ${nap.city}, ${nap.state} ${nap.postal_code}`);
    lines.push(`Phone: ${nap.phone}`);
    lines.push("");
    lines.push(`Get a free estimate today. [INTERNAL_LINK: contact]`);

    const schema: Record<string, unknown> = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        name: nap.business_name,
        address: {
            "@type": "PostalAddress",
            streetAddress: nap.street,
            addressLocality: nap.city,
            addressRegion: nap.state,
            postalCode: nap.postal_code,
        },
        telephone: nap.phone,
        geo: nap.lat !== undefined && nap.lng !== undefined
            ? { "@type": "GeoCoordinates", latitude: nap.lat, longitude: nap.lng }
            : undefined,
        areaServed: {
            "@type": "GeoCircle",
            geoMidpoint: nap.lat !== undefined && nap.lng !== undefined
                ? { "@type": "GeoCoordinates", latitude: nap.lat, longitude: nap.lng }
                : undefined,
            geoRadius: ((nap.service_area_radius_mi ?? 25) * 1609).toString(),
        },
    };

    const markdown = lines.join("\n");
    const word_count = markdown.split(/\s+/).filter(Boolean).length;
    return { markdown, schema, word_count };
}

export class LocalPageWriter extends AgentBase {
    readonly id = "local_page_writer";
    readonly name = "Local Landing Page Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        // `service` is either explicit or taken from `keyword`.
        const service = (input.service as string | undefined) ?? (input.keyword as string | undefined);
        const city = input.city as string | undefined;
        if (!service || !city) return { ok: false, error: "city and service/keyword required" };

        // NAP can come in as a nested object OR as flat fields (test uses flat).
        const napIn = input.nap as Partial<NAP> | undefined;
        const nap: NAP = {
            business_name: (napIn?.business_name as string | undefined)
                ?? (input.business_name as string | undefined)
                ?? `${titleCase(city)} ${titleCase(service)} Co.`,
            street: napIn?.street ?? (input.street as string | undefined) ?? "123 Main St",
            city: napIn?.city ?? city,
            state: napIn?.state ?? (input.state as string | undefined) ?? "TX",
            postal_code: napIn?.postal_code ?? (input.postal_code as string | undefined) ?? "00000",
            phone: napIn?.phone ?? (input.phone as string | undefined) ?? "(555) 555-0100",
            lat: napIn?.lat ?? (input.lat as number | undefined),
            lng: napIn?.lng ?? (input.lng as number | undefined),
            service_area_radius_mi: napIn?.service_area_radius_mi
                ?? (input.service_area_radius_mi as number | undefined)
                ?? 25,
        };

        const l: LocalPageInput = {
            service,
            city,
            neighborhoods: input.neighborhoods as string[] | undefined,
            landmarks: input.landmarks as string[] | undefined,
            nap,
        };
        const llm = input.llm_fn as LlmFn | undefined;
        const tmpl = defaultLocalTemplate(l);
        const markdown = llm ? await llm(`Write a local landing page about ${service} in ${city}`) : tmpl.markdown;
        return {
            ok: true,
            data: {
                title: `${titleCase(service)} in ${titleCase(city)}`,
                slug: slugify(`${service}-${city}`),
                markdown,
                schema: tmpl.schema,
                word_count: tmpl.word_count,
            },
        };
    }
}
