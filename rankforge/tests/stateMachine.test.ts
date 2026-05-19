import { test } from "node:test";
import assert from "node:assert/strict";
import { SiteStateMachine, isValidTransition } from "../src/agents/group01/siteStateMachine.ts";
import { db } from "../src/core/db.ts";

test("isValidTransition: new → crawling", () => {
    assert.equal(isValidTransition("new", "crawling"), true);
});

test("isValidTransition: rejects new → live (skip ahead)", () => {
    assert.equal(isValidTransition("new", "live"), false);
});

test("isValidTransition: live → generating (re-loop)", () => {
    assert.equal(isValidTransition("live", "generating"), true);
});

test("SiteStateMachine: valid transition updates site state", async () => {
    const site = await db.createSite("https://example.com");
    const machine = new SiteStateMachine();
    const out = await machine.run({ site_id: site.id, to: "crawling", reason: "test" });
    assert.equal(out.ok, true);
    const after = await db.getSite(site.id);
    assert.equal(after?.state, "crawling");
});

test("SiteStateMachine: invalid transition is rejected", async () => {
    const site = await db.createSite("https://example2.com");
    const machine = new SiteStateMachine();
    const out = await machine.run({ site_id: site.id, to: "live", reason: "trying to skip" });
    assert.equal(out.ok, false);
    const after = await db.getSite(site.id);
    assert.equal(after?.state, "new"); // unchanged
});
