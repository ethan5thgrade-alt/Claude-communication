import { test } from "node:test";
import assert from "node:assert/strict";
import { GrandOrchestrator } from "../src/agents/group01/grandOrchestrator.ts";
import { db } from "../src/core/db.ts";
import type { Site } from "../src/core/types.ts";

test("GrandOrchestrator ranks agency > pro > starter > free at equal urgency", () => {
    const orch = new GrandOrchestrator();
    const now = new Date().toISOString();
    const baseSite = (tier: Site["plan_tier"]): Site => ({
        id: tier,
        url: `https://${tier}.example.com`,
        plan_tier: tier,
        state: "new",
        state_updated_at: now,
        paused: false,
        timezone: "UTC",
        urgency: 5,
        last_run_at: now,
        config: null,
        created_at: now,
    });
    const ranked = orch.rank([baseSite("free"), baseSite("starter"), baseSite("pro"), baseSite("agency")]);
    assert.deepEqual(ranked.map(s => s.plan_tier), ["agency", "pro", "starter", "free"]);
});

test("GrandOrchestrator ranks higher-urgency before lower-urgency within same tier", () => {
    const orch = new GrandOrchestrator();
    const now = new Date().toISOString();
    const mk = (id: string, urgency: number): Site => ({
        id, url: `https://${id}.example.com`, plan_tier: "pro", state: "new",
        state_updated_at: now, paused: false, timezone: "UTC", urgency,
        last_run_at: now, config: null, created_at: now,
    });
    const ranked = orch.rank([mk("a", 3), mk("b", 9), mk("c", 5)]);
    assert.equal(ranked[0].id, "b");
    assert.equal(ranked[1].id, "c");
    assert.equal(ranked[2].id, "a");
});

test("GrandOrchestrator one-shot sweep dispatches tasks for paused=false sites", async () => {
    const site = await db.createSite("https://orchestrator-test.com", "pro");
    const orch = new GrandOrchestrator();
    const out = await orch.run({ one_shot: true });
    assert.equal(out.ok, true);
    const stats = out.data as { dispatched: number; sites_scanned: number };
    assert.ok(stats.sites_scanned >= 1);
    // a task should have been queued for site_crawler (next agent for "new")
    const tasks = await db.listTasks({ assigned_to: "site_crawler", site_id: site.id });
    assert.ok(tasks.length >= 1, `expected a site_crawler task for ${site.id}, got ${tasks.length}`);
});
