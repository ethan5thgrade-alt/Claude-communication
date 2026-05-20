// 019 — Site Architecture Mapper.
// Build internal-link graph, compute click depth, find hubs/orphans/silos.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";
import type { ParsedPage } from "./htmlParser.ts";

export interface ArchitectureGraph {
    nodes: { url: string; in_degree: number; out_degree: number; click_depth: number | null }[];
    edges: { from: string; to: string }[];
    hubs: string[];        // top 5 by in_degree
    orphans: string[];     // in_degree = 0 (excluding homepage)
    avg_click_depth: number;
}

function bfsDepths(homepage: string, adj: Map<string, Set<string>>): Map<string, number> {
    const depths = new Map<string, number>();
    depths.set(homepage, 0);
    const queue = [homepage];
    while (queue.length) {
        const cur = queue.shift()!;
        const d = depths.get(cur)!;
        for (const next of adj.get(cur) ?? []) {
            if (!depths.has(next)) {
                depths.set(next, d + 1);
                queue.push(next);
            }
        }
    }
    return depths;
}

export function buildGraph(pages: ParsedPage[], homepage?: string): ArchitectureGraph {
    const urls = new Set(pages.map(p => p.final_url));
    const adj = new Map<string, Set<string>>();
    const inDeg = new Map<string, number>();
    const edges: { from: string; to: string }[] = [];
    for (const u of urls) { adj.set(u, new Set()); inDeg.set(u, 0); }
    for (const page of pages) {
        for (const link of page.links) {
            if (!link.internal) continue;
            let abs: string;
            try { abs = new URL(link.href, page.final_url).href; } catch { continue; }
            if (!urls.has(abs)) continue;
            if (abs === page.final_url) continue;
            if (!adj.get(page.final_url)!.has(abs)) {
                adj.get(page.final_url)!.add(abs);
                edges.push({ from: page.final_url, to: abs });
                inDeg.set(abs, (inDeg.get(abs) ?? 0) + 1);
            }
        }
    }
    const home = homepage ?? pages[0]?.final_url ?? "";
    const depths = home ? bfsDepths(home, adj) : new Map<string, number>();
    const nodes = Array.from(urls).map(u => ({
        url: u,
        in_degree: inDeg.get(u) ?? 0,
        out_degree: (adj.get(u)?.size ?? 0),
        click_depth: depths.get(u) ?? null,
    }));
    const hubs = [...nodes].sort((a, b) => b.in_degree - a.in_degree).slice(0, 5).map(n => n.url);
    const orphans = nodes.filter(n => n.in_degree === 0 && n.url !== home).map(n => n.url);
    const knownDepths = nodes.map(n => n.click_depth).filter((d): d is number => d !== null);
    const avgDepth = knownDepths.length ? knownDepths.reduce((s, d) => s + d, 0) / knownDepths.length : 0;
    return { nodes, edges, hubs, orphans, avg_click_depth: avgDepth };
}

export class ArchitectureMapper extends AgentBase {
    readonly id = "architecture_mapper";
    readonly name = "Site Architecture Mapper";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const parsed = (input.parsed as ParsedPage[] | undefined) ?? [];
        if (parsed.length === 0) return { ok: false, error: "no parsed pages" };
        const graph = buildGraph(parsed, input.homepage as string | undefined);
        return { ok: true, data: graph };
    }
}
