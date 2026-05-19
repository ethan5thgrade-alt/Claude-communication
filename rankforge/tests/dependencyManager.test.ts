import { test } from "node:test";
import assert from "node:assert/strict";
import {
    PIPELINE_DEPS, hasCycle, getReadyAgents, DependencyManager,
} from "../src/agents/group01/dependencyManager.ts";

test("PIPELINE_DEPS has no cycles", () => {
    const r = hasCycle(PIPELINE_DEPS);
    assert.equal(r.cycle, false);
});

test("hasCycle: detects a deliberate cycle", () => {
    const r = hasCycle({ a: ["b"], b: ["c"], c: ["a"] });
    assert.equal(r.cycle, true);
    assert.ok(r.path && r.path.length >= 3);
});

test("getReadyAgents: returns agents with all upstream completed", () => {
    const ready = getReadyAgents(PIPELINE_DEPS, new Set(["site_crawler"]));
    // site_crawler done → html_deep_parser is ready (and so is anything else with empty deps)
    assert.ok(ready.includes("html_deep_parser"));
});

test("getReadyAgents: doesn't return already-completed agents", () => {
    const ready = getReadyAgents(PIPELINE_DEPS, new Set(["site_crawler"]));
    assert.ok(!ready.includes("site_crawler"));
});

test("getReadyAgents: nothing further until upstream finishes", () => {
    const ready = getReadyAgents(PIPELINE_DEPS, new Set());
    // Only site_crawler should be ready (its deps = [])
    assert.deepEqual(ready, ["site_crawler"]);
});

test("DependencyManager: reports cycle in user-supplied graph", async () => {
    const dm = new DependencyManager();
    const out = await dm.run({ graph: { a: ["b"], b: ["a"] }, completed: [] });
    assert.equal(out.ok, false);
});
