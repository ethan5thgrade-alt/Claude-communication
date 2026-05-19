import { test } from "node:test";
import assert from "node:assert/strict";
import { allocateSlots } from "../src/agents/group01/priorityArbitrator.ts";

test("allocateSlots: divides capacity by tier weights", () => {
    const plan = allocateSlots(100, { agency: 50, pro: 50, starter: 50, free: 50 });
    assert.equal(plan.perTier.agency, 40);
    assert.equal(plan.perTier.pro, 30);
    assert.equal(plan.perTier.starter, 20);
    assert.equal(plan.perTier.free, 10);
});

test("allocateSlots: starvation prevention — free always gets >=1", () => {
    // Capacity 5, weights would give free 0.5 → floor 0. But there's demand,
    // so free still gets 1.
    const plan = allocateSlots(5, { agency: 0, pro: 0, starter: 0, free: 5 });
    assert.ok(plan.perTier.free >= 1, `expected free>=1, got ${plan.perTier.free}`);
});

test("allocateSlots: redistributes slack from unfilled tiers", () => {
    // No agency demand → agency's 40 slots redistribute.
    const plan = allocateSlots(100, { agency: 0, pro: 100, starter: 0, free: 0 });
    assert.equal(plan.perTier.pro, 100);
});

test("allocateSlots: respects demand cap", () => {
    const plan = allocateSlots(100, { agency: 5, pro: 5, starter: 5, free: 5 });
    assert.equal(plan.perTier.agency, 5);
    assert.equal(plan.perTier.pro, 5);
    assert.equal(plan.perTier.starter, 5);
    assert.equal(plan.perTier.free, 5);
});

test("allocateSlots: zero capacity → zero everywhere", () => {
    const plan = allocateSlots(0, { agency: 10, pro: 10, starter: 10, free: 10 });
    assert.equal(plan.perTier.agency, 0);
    assert.equal(plan.perTier.pro, 0);
    assert.equal(plan.perTier.starter, 0);
    assert.equal(plan.perTier.free, 0);
});
