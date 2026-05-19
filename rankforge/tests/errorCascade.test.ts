import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyError, ErrorCascade, RETRY_DELAYS_S } from "../src/agents/group01/errorCascade.ts";

test("classify: 429 → rate_limit", () => {
    assert.equal(classifyError({ status: 429 }), "rate_limit");
});
test("classify: 401/403 → auth", () => {
    assert.equal(classifyError({ status: 401 }), "auth");
    assert.equal(classifyError({ status: 403 }), "auth");
});
test("classify: 500 → transient", () => {
    assert.equal(classifyError({ status: 503, message: "service unavailable" }), "transient");
});
test("classify: ECONNRESET → transient", () => {
    assert.equal(classifyError({ message: "socket hang up ECONNRESET" }), "transient");
});
test("classify: validation message → data", () => {
    assert.equal(classifyError({ message: "Invalid input" }), "data");
});
test("classify: 404 → permanent", () => {
    assert.equal(classifyError({ status: 404 }), "permanent");
});
test("classify: unknown text → unknown", () => {
    assert.equal(classifyError({ message: "something weird happened" }), "unknown");
});

test("ErrorCascade: transient triggers retry with backoff", async () => {
    const c = new ErrorCascade();
    const out = await c.run({
        failed_agent_id: "x",
        attempt: 1,
        error: { status: 503 },
    });
    assert.equal(out.ok, true);
    const action = out.artifacts as { kind: string; delay_s: number };
    assert.equal(action.kind, "retry");
    assert.equal(action.delay_s, RETRY_DELAYS_S[0]);
});

test("ErrorCascade: auth error triggers alert", async () => {
    const c = new ErrorCascade();
    const out = await c.run({
        failed_agent_id: "x",
        attempt: 1,
        error: { status: 401 },
    });
    const action = out.artifacts as { kind: string };
    assert.equal(action.kind, "alert");
});

test("ErrorCascade: transient after max attempts gives up", async () => {
    const c = new ErrorCascade();
    const out = await c.run({
        failed_agent_id: "x",
        attempt: RETRY_DELAYS_S.length + 1,
        error: { status: 503 },
    });
    const action = out.artifacts as { kind: string };
    assert.equal(action.kind, "give_up");
});
