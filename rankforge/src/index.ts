// RankForge entry point.
// Registers Group 1 agents and starts the Grand Orchestrator's continuous loop.

import { registerGroup01 } from "./agents/group01/index.ts";
import { getAgent } from "./core/registry.ts";
import { getMesh, meshEnabled } from "./core/meshBridge.ts";
import type { GrandOrchestrator } from "./agents/group01/grandOrchestrator.ts";

async function main(): Promise<void> {
    const agents = registerGroup01();
    console.log(`[rankforge] registered ${Object.keys(agents).length} Group-1 agents`);

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
