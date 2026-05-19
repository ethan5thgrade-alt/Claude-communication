// 006 — Dependency Graph Manager.
// Maintains a DAG of agent dependencies. Before dispatching any agent,
// confirms upstream outputs exist. Detects cycles.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

// Canonical pipeline DAG. Edges = "X depends on Y" → Y must run first.
// Keys are agent ids, values are the agents whose output this one needs.
export const PIPELINE_DEPS: Record<string, string[]> = {
    // Group 2 — crawl
    site_crawler: [],
    html_deep_parser: ["site_crawler"],
    technical_seo_auditor: ["html_deep_parser"],
    // Group 3 — keywords
    keyword_seed_generator: ["technical_seo_auditor"],
    keyword_expander: ["keyword_seed_generator"],
    keyword_clusterer: ["keyword_expander"],
    // Group 4 — content
    content_brief_writer: ["keyword_clusterer"],
    content_drafter: ["content_brief_writer"],
    content_polisher: ["content_drafter"],
    // Group 1 — quality gate
    quality_gatekeeper: ["content_polisher"],
    // Group 7 — publishing
    publisher_router: ["quality_gatekeeper"],
    // Loop back
    rank_tracking_engine: ["publisher_router"],
};

export function hasCycle(graph: Record<string, string[]>): { cycle: boolean; path?: string[] } {
    const visiting = new Set<string>();
    const visited = new Set<string>();
    const stack: string[] = [];

    const dfs = (node: string): string[] | null => {
        if (visiting.has(node)) {
            return [...stack, node];
        }
        if (visited.has(node)) return null;
        visiting.add(node);
        stack.push(node);
        for (const dep of graph[node] ?? []) {
            const found = dfs(dep);
            if (found) return found;
        }
        stack.pop();
        visiting.delete(node);
        visited.add(node);
        return null;
    };
    for (const n of Object.keys(graph)) {
        const found = dfs(n);
        if (found) return { cycle: true, path: found };
    }
    return { cycle: false };
}

/**
 * Returns the agents whose dependencies are fully satisfied — i.e. for each
 * required upstream agent, a successful row exists in `completedAgents`.
 */
export function getReadyAgents(
    graph: Record<string, string[]>,
    completedAgents: Set<string>,
): string[] {
    const ready: string[] = [];
    for (const [agent, deps] of Object.entries(graph)) {
        if (completedAgents.has(agent)) continue;
        if (deps.every(d => completedAgents.has(d))) ready.push(agent);
    }
    return ready;
}

export class DependencyManager extends AgentBase {
    readonly id = "dependency_manager";
    readonly name = "Dependency Graph Manager";
    readonly group = 1;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        // input: { graph?: ..., completed: string[] }   — defaults to PIPELINE_DEPS
        const graph = (input.graph as Record<string, string[]> | undefined) ?? PIPELINE_DEPS;
        const completed = new Set((input.completed as string[] | undefined) ?? []);
        const cyc = hasCycle(graph);
        if (cyc.cycle) {
            this.log({
                message: `CYCLE DETECTED: ${cyc.path?.join(" → ")}`,
            }, "error");
            await this.notify(`Dependency cycle detected: ${cyc.path?.join(" → ")}`, "critical");
            return { ok: false, error: "dependency cycle", data: { cycle: cyc.path } };
        }
        const ready = getReadyAgents(graph, completed);
        return { ok: true, data: { ready, total: Object.keys(graph).length, completed: completed.size } };
    }
}
