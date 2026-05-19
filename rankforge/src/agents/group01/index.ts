// Group 1 — Grand Orchestration. Convenience exports + auto-registry helper.

import { AgentBase } from "../../core/AgentBase.ts";
import { registerAgent } from "../../core/registry.ts";
import { GrandOrchestrator } from "./grandOrchestrator.ts";
import { SiteStateMachine } from "./siteStateMachine.ts";
import { QualityGatekeeper } from "./qualityGatekeeper.ts";
import { ErrorCascade } from "./errorCascade.ts";
import { PriorityArbitrator } from "./priorityArbitrator.ts";
import { DependencyManager } from "./dependencyManager.ts";
import { ResourceGovernor } from "./resourceGovernor.ts";
import { HealthMonitor } from "./healthMonitor.ts";
import { HumanBridge } from "./humanBridge.ts";
import { SystemClock } from "./systemClock.ts";

export * from "./grandOrchestrator.ts";
export * from "./siteStateMachine.ts";
export * from "./qualityGatekeeper.ts";
export * from "./errorCascade.ts";
export * from "./priorityArbitrator.ts";
export * from "./dependencyManager.ts";
export * from "./resourceGovernor.ts";
export * from "./healthMonitor.ts";
export * from "./humanBridge.ts";
export * from "./systemClock.ts";

/** Instantiate and register all 10 Group 1 agents. Returns the registry map. */
export function registerGroup01(): Record<string, AgentBase> {
    const all: Record<string, AgentBase> = {
        grand_orchestrator: new GrandOrchestrator(),
        site_state_machine: new SiteStateMachine(),
        quality_gatekeeper: new QualityGatekeeper(),
        error_cascade: new ErrorCascade(),
        priority_arbitrator: new PriorityArbitrator(),
        dependency_manager: new DependencyManager(),
        resource_governor: new ResourceGovernor(),
        health_monitor: new HealthMonitor(),
        human_bridge: new HumanBridge(),
        system_clock: new SystemClock(),
    };
    for (const a of Object.values(all)) registerAgent(a);
    return all;
}
