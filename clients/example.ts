/**
 * Minimal Agent Mesh client demo.
 *
 *   bun run example.ts
 *   npx tsx example.ts
 *
 * Assumes a broker is running at ws://localhost:8766. Set BROKER_URL,
 * INSTANCE_ID, INSTANCE_NAME, PROJECT env vars to customize.
 */
import { connectMesh } from "./connect.js";

// Minimal Node global typing so this file compiles without `@types/node`.
// When `@types/node` is installed it takes precedence over this declaration.
declare const process: {
  env: Record<string, string | undefined>;
  on(event: "SIGINT" | "SIGTERM", listener: () => void): void;
  exit(code?: number): never;
};

const id = process.env.INSTANCE_ID ?? "ts1";
const name = process.env.INSTANCE_NAME ?? "TS Demo";
const project = process.env.PROJECT ?? "OPTFINDER";
const brokerUrl = process.env.BROKER_URL ?? "ws://localhost:8766";
const token = process.env.MESH_TOKEN;

async function main() {
  const mesh = await connectMesh({ id, name, project, brokerUrl, token });

  mesh.on("message", (evt) => {
    console.log(`[message from ${evt.from}] ${evt.text}`);
  });

  mesh.on("task_assigned", (evt) => {
    const t = evt.task;
    console.log(`[task_assigned] ${t.id} "${t.title}" (by ${t.created_by})`);
    // Acknowledge by claiming + bumping status. Replace with real work.
    mesh.taskStatus(t.id, "In Progress");
  });

  mesh.on("task_completed", (evt) => {
    const t = evt.task;
    console.log(`[task_completed] ${t.id} done by ${t.done_by}: ${t.result ?? ""}`);
  });

  mesh.on("memory_write", (evt) => {
    const m = evt.memory;
    console.log(`[memory] ${m.key} = ${JSON.stringify(m.value)} (${m.type}, by ${m.by})`);
  });

  mesh.on("control", (evt) => {
    console.log(`[control] paused=${evt.paused}`);
  });

  // Greet the human watcher.
  mesh.send("TypeScript client online.");
  mesh.status("Idle, listening", 0);

  // Hold the process open until SIGINT.
  const shutdown = () => {
    console.log("\nShutting down...");
    mesh.disconnect();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  // Print a heartbeat every 30s so the user sees the process is alive.
  setInterval(() => {
    if (mesh.connected) console.log("[heartbeat] still connected");
  }, 30_000);
}

main().catch((err) => {
  console.error("Failed to connect:", err);
  process.exit(1);
});
