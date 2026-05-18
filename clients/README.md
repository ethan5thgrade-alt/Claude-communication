# Agent Mesh — TypeScript client

A zero-dependency TypeScript port of `connect.py`. Lets Node 22+/Bun/Deno/browser
processes join the same broker that the Python instances use.

## Install / use

There is no npm publish step required for local use — just import `connect.ts`
directly from this folder. If you want a published package, run the `tsup`
build (recipe below).

## Quickstart

Make sure the broker is running:

```bash
cd ..
python3 broker.py
```

Then in another terminal:

```bash
# Bun (recommended — no extra setup)
bun run example.ts

# Node 22+ via tsx
npx tsx example.ts

# Node 22+ direct (requires --experimental-strip-types or .ts loader)
node --experimental-strip-types example.ts
```

Customize via env vars:

```bash
INSTANCE_ID=ts1 INSTANCE_NAME="TS Bot" PROJECT=OPTFINDER \
BROKER_URL=ws://localhost:8766 \
bun run example.ts
```

## Library usage

```ts
import { connectMesh } from "./connect.js";

const mesh = await connectMesh({
  id: "ts1",
  name: "TS Bot",
  project: "OPTFINDER",
  brokerUrl: "ws://localhost:8766",     // optional, default ws://localhost:8766
  token: process.env.MESH_TOKEN,         // optional, batch-4 auth token
});

// Outgoing helpers — mirror connect.py
mesh.send("Task complete.");                    // → human
mesh.send("Match my format.", "cc2");           // → another instance
mesh.broadcast("API contract finalized.");
mesh.status("Writing SSE endpoint", 80);
mesh.memory("SSE_FORMAT", "{pct, ticker}", "contract");
mesh.taskCreate("Write CSV parser", "cc2", "high");
mesh.taskClaim("T003");
mesh.taskStatus("T003", "Review");
mesh.taskDone("T003", "merged in PR #41");

// Incoming events — typed discriminated union
mesh.on("message", (e) => console.log(`[${e.from}] ${e.text}`));
mesh.on("task_assigned", (e) => console.log(`assigned: ${e.task.id}`));
mesh.on("task_completed", (e) => console.log(`done: ${e.task.id}`));
mesh.on("memory_write", (e) => console.log(`memory: ${e.memory.key}`));
mesh.on("control", (e) => console.log(`paused=${e.paused}`));

// Wildcard handler
mesh.on("*", (e) => console.log("event:", e.type));

// Graceful shutdown
process.on("SIGINT", () => {
  mesh.disconnect();
  process.exit(0);
});
```

## Auto-reconnect

The client reconnects automatically with exponential backoff capped at 30s —
identical behaviour to `connect.py`. Call `disconnect()` to stop permanently.

## Runtime requirements

- **Node 22+** — uses the built-in global `WebSocket`. No `ws` package needed.
- **Bun** — works out of the box.
- **Deno** — works out of the box.
- **Browsers** — works out of the box.
- **Node <22** — install `ws` and pass it explicitly:

  ```ts
  import WebSocket from "ws";
  const mesh = await connectMesh({
    id: "ts1", name: "TS", project: "P",
    websocketImpl: WebSocket as unknown as typeof globalThis.WebSocket,
  });
  ```

## Smoke test against a running broker

```bash
# Terminal 1
cd .. && python3 broker.py

# Terminal 2 — start the TS client
INSTANCE_ID=ts1 bun run example.ts

# Terminal 3 — send a message to ts1 from the broker REST API
curl -X POST http://localhost:8765/api/send \
     -H 'Content-Type: application/json' \
     -d '{"to":"ts1","text":"hello from curl"}'
# Terminal 2 should print:
# [message from you] hello from curl
```

You can also send a broadcast and watch the TS client receive it:

```bash
curl -X POST http://localhost:8765/api/send \
     -H 'Content-Type: application/json' \
     -d '{"to":"all","text":"broadcast test"}'
```

## Building a dual ESM/CJS package (optional)

If you want a published npm artifact, add devDependencies and a tsup config:

```bash
npm i -D tsup typescript tsx
```

Add to `package.json`:

```json
{
  "scripts": {
    "build": "tsup connect.ts --format esm,cjs --dts --clean"
  }
}
```

Then:

```bash
npm run build
# Output in dist/: connect.mjs, connect.cjs, connect.d.ts
```

## Type definitions

All event payloads are modelled as a discriminated union in `connect.ts`:

```ts
export type IncomingEvent =
  | { type: "message"; from: string; to: string; text: string; ts?: string; id?: string }
  | { type: "memory_write"; memory: MeshMemory }
  | { type: "memory_init"; memory: MeshMemory[]; ts: string }
  | { type: "tasks_init"; tasks: MeshTask[]; ts: string }
  | { type: "task_assigned"; task: MeshTask }
  | { type: "task_completed"; task: MeshTask }
  | { type: "backlog"; messages: IncomingEvent[] }
  | { type: "approval_decision"; id: string; action: string; decision: boolean }
  | { type: "approval_request"; approval: MeshApproval }
  | { type: "control"; paused: boolean }
  | { type: "error"; error: string; ref?: string }
  | { type: string; [k: string]: unknown };  // fallback for forward-compat
```

`mesh.on("message", h)` narrows the handler's argument to the right variant via
the discriminator — your IDE will autocomplete `e.from`, `e.text`, etc.

## File map

```
clients/
├── connect.ts      # The client — single file, no runtime deps
├── example.ts      # Demo script
├── package.json
├── tsconfig.json   # strict, ES2022, ESNext modules
└── README.md
```
