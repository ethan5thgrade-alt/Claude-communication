// Agent registry — maps agent ids to instances. Used by the GrandOrchestrator
// (and the in-process AgentBus) to find an agent class to dispatch.

import type { AgentBase } from "./AgentBase.ts";

const _registry = new Map<string, AgentBase>();

export function registerAgent(agent: AgentBase): void {
    _registry.set(agent.id, agent);
}

export function getAgent(id: string): AgentBase | undefined {
    return _registry.get(id);
}

export function allAgents(): AgentBase[] {
    return Array.from(_registry.values());
}

export function agentsByGroup(group: number): AgentBase[] {
    return allAgents().filter(a => a.group === group);
}
