/**
 * Test harness that drives the real TypeScript MeshClient from connect.ts.
 *
 * Used by tests/test_broker.py to exercise approveAndWait / voteAndWait against
 * a live broker. Node 22+ strips the TS types on import; the global WebSocket is
 * used by the client. The harness prints exactly one JSON line of the form
 *   {"ok": true, "result": <value>}
 * to stdout on success, or {"ok": false, "error": "..."} on failure.
 *
 * Invocation (env-driven so quoting stays simple):
 *   BROKER_URL=ws://localhost:PORT MODE=approve|vote|approve_timeout|vote_timeout \
 *   INSTANCE_ID=tsapprove node tests/ts_client_harness.mjs
 */
import { connectMesh } from "../clients/connect.ts";

const brokerUrl = process.env.BROKER_URL || "ws://localhost:8766";
const id = process.env.INSTANCE_ID || "ts1";
const mode = process.env.MODE || "approve";

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function main() {
  const mesh = await connectMesh({
    id,
    name: "TS Harness",
    project: "P",
    brokerUrl,
    quiet: true,
  });

  let result;
  if (mode === "approve") {
    // Block on a human decision. The test sends approval_decision over the UI.
    result = await mesh.approveAndWait("ts deploy", "medium", "harness", 5_000);
  } else if (mode === "approve_timeout") {
    // No decision will ever arrive; expect null after the short timeout.
    result = await mesh.approveAndWait("ts noop", "low", "", 400);
  } else if (mode === "vote") {
    // Create a vote with threshold 2; two instances cast "yes" -> resolves.
    result = await mesh.voteAndWait("ship it?", ["yes", "no"], 2, 5_000);
  } else if (mode === "vote_timeout") {
    // threshold 99 can never be met; expect null after the short timeout.
    result = await mesh.voteAndWait("never?", ["yes", "no"], 99, 400);
  } else {
    throw new Error(`unknown MODE=${mode}`);
  }

  emit({ ok: true, result });
  mesh.disconnect();
  // Give the close frame a tick to flush before exit.
  setTimeout(() => process.exit(0), 50);
}

main().catch((err) => {
  emit({ ok: false, error: String((err && err.message) || err) });
  process.exit(1);
});
