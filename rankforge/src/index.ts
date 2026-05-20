// RankForge entry point.
// Registers Group 1 agents and starts the Grand Orchestrator's continuous loop.

import { registerGroup01 } from "./agents/group01/index.ts";
import { registerGroup02 } from "./agents/group02/index.ts";
import { registerGroup03 } from "./agents/group03/index.ts";
import { getAgent } from "./core/registry.ts";
import { getMesh, meshEnabled } from "./core/meshBridge.ts";
import type { GrandOrchestrator } from "./agents/group01/grandOrchestrator.ts";

async function main(): Promise<void> {
    const g1 = registerGroup01();
    const g2 = registerGroup02();
    const g3 = registerGroup03();
    const agents = { ...g1, ...g2, ...g3 };
    console.log(`[rankforge] registered ${Object.keys(g1).length} Group-1 + ${Object.keys(g2).length} Group-2 + ${Object.keys(g3).length} Group-3 agents`);

    if (meshEnabled()) {
        getMesh("rankforge", "RankForge (Group 1)");
        console.log(`[rankforge] connected to Agent Mesh broker`);
    } else {
        console.log(`[rankforge] mesh disabled (set MESH_BROKER_URL to enable)`);
    }

    // Boot the orchestrator's continuous loop.
    const orchestrator = getAgent("grand_orchestrator") as GrandOrchestrator;
    console.log(`[rankforge] starting Grand Orchestrator loop (every 60s)`);
    await orchestrator.execute({ one_shot: false });

    // Graceful shutdown
    const shutdown = () => {
        console.log("[rankforge] shutting down...");
        orchestrator.stop();
        setTimeout(() => process.exit(0), 500);
    };
    process.on("SIGTERM", shutdown);
    process.on("SIGINT", shutdown);
}

main().catch((err) => {
    console.error("[rankforge] fatal:", err);
    process.exit(1);
});
