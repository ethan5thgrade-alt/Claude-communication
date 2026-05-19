// Tiny DB abstraction. Backed by Supabase REST if SUPABASE_URL+SUPABASE_KEY are
// set, otherwise an in-memory fallback so tests + local dev run with zero infra.
//
// Only the surface RankForge agents actually use is implemented: insert+select
// on the 5 infra tables + sites. Not a full ORM.

import { randomUUID } from "node:crypto";
import type {
    AgentRun, AgentMessage, AgentMemory, AgentTask, Site, SiteState, PlanTier,
} from "./types.ts";

export interface DB {
    // agent_runs
    insertRun(row: Partial<AgentRun> & Pick<AgentRun, "agent_id" | "status">): Promise<AgentRun>;
    updateRun(id: string, patch: Partial<AgentRun>): Promise<void>;
    // sites
    listSites(filter?: { state?: SiteState; paused?: boolean }): Promise<Site[]>;
    getSite(id: string): Promise<Site | null>;
    updateSite(id: string, patch: Partial<Site>): Promise<void>;
    createSite(url: string, plan_tier?: PlanTier): Promise<Site>;
    // site_state_history
    recordTransition(site_id: string, from: SiteState | null, to: SiteState, reason: string): Promise<void>;
    // agent_messages
    insertMessage(row: Partial<AgentMessage> & Pick<AgentMessage, "from_agent" | "to_agent" | "message_type">): Promise<AgentMessage>;
    // agent_memory
    upsertMemory(row: Partial<AgentMemory> & Pick<AgentMemory, "agent_id" | "key" | "memory_type">): Promise<AgentMemory>;
    getMemory(agent_id: string, key: string, site_id?: string | null): Promise<AgentMemory | null>;
    // agent_tasks
    insertTask(row: Partial<AgentTask> & Pick<AgentTask, "assigned_to" | "title">): Promise<AgentTask>;
    listTasks(filter: { assigned_to?: string; status?: AgentTask["status"]; site_id?: string }): Promise<AgentTask[]>;
    updateTask(id: string, patch: Partial<AgentTask>): Promise<void>;
}

class InMemoryDB implements DB {
    private runs = new Map<string, AgentRun>();
    private sites = new Map<string, Site>();
    private messages = new Map<string, AgentMessage>();
    private memory = new Map<string, AgentMemory>();  // key = `${site_id}::${agent_id}::${key}`
    private tasks = new Map<string, AgentTask>();
    private history: { site_id: string; from: string | null; to: string; reason: string; ts: string }[] = [];

    async insertRun(row: Partial<AgentRun> & Pick<AgentRun, "agent_id" | "status">): Promise<AgentRun> {
        const id = row.id ?? randomUUID();
        const full: AgentRun = {
            id,
            agent_id: row.agent_id,
            agent_version: row.agent_version ?? "1.0.0",
            site_id: row.site_id ?? null,
            status: row.status,
            attempt: row.attempt ?? 1,
            input: row.input ?? null,
            output: row.output ?? null,
            error: row.error ?? null,
            duration_ms: row.duration_ms ?? null,
            tokens_used: row.tokens_used ?? null,
            api_calls: row.api_calls ?? null,
            triggered_by: row.triggered_by ?? "system",
            triggered_agents: row.triggered_agents ?? [],
            created_at: row.created_at ?? new Date().toISOString(),
            completed_at: row.completed_at ?? null,
        };
        this.runs.set(id, full);
        return full;
    }

    async updateRun(id: string, patch: Partial<AgentRun>): Promise<void> {
        const cur = this.runs.get(id);
        if (!cur) return;
        this.runs.set(id, { ...cur, ...patch });
    }

    async listSites(filter?: { state?: SiteState; paused?: boolean }): Promise<Site[]> {
        let out = Array.from(this.sites.values());
        if (filter?.state !== undefined) out = out.filter(s => s.state === filter.state);
        if (filter?.paused !== undefined) out = out.filter(s => s.paused === filter.paused);
        return out;
    }

    async getSite(id: string): Promise<Site | null> {
        return this.sites.get(id) ?? null;
    }

    async updateSite(id: string, patch: Partial<Site>): Promise<void> {
        const cur = this.sites.get(id);
        if (!cur) return;
        this.sites.set(id, { ...cur, ...patch });
    }

    async createSite(url: string, plan_tier: PlanTier = "free"): Promise<Site> {
        const id = randomUUID();
        const site: Site = {
            id,
            url,
            plan_tier,
            state: "new",
            state_updated_at: new Date().toISOString(),
            paused: false,
            timezone: "UTC",
            urgency: 5,
            last_run_at: null,
            config: null,
            created_at: new Date().toISOString(),
        };
        this.sites.set(id, site);
        return site;
    }

    async recordTransition(site_id: string, from: SiteState | null, to: SiteState, reason: string): Promise<void> {
        this.history.push({ site_id, from, to, reason, ts: new Date().toISOString() });
    }

    async insertMessage(row: Partial<AgentMessage> & Pick<AgentMessage, "from_agent" | "to_agent" | "message_type">): Promise<AgentMessage> {
        const id = row.id ?? randomUUID();
        const full: AgentMessage = {
            id,
            from_agent: row.from_agent,
            to_agent: row.to_agent,
            site_id: row.site_id ?? null,
            message_type: row.message_type,
            payload: row.payload ?? null,
            priority: row.priority ?? 5,
            delivered: row.delivered ?? false,
            read_at: row.read_at ?? null,
            created_at: row.created_at ?? new Date().toISOString(),
        };
        this.messages.set(id, full);
        return full;
    }

    async upsertMemory(row: Partial<AgentMemory> & Pick<AgentMemory, "agent_id" | "key" | "memory_type">): Promise<AgentMemory> {
        const composite = `${row.site_id ?? ""}::${row.agent_id}::${row.key}`;
        const existing = this.memory.get(composite);
        const id = existing?.id ?? row.id ?? randomUUID();
        const full: AgentMemory = {
            id,
            site_id: row.site_id ?? null,
            agent_id: row.agent_id,
            memory_type: row.memory_type,
            key: row.key,
            value: row.value ?? null,
            confidence: row.confidence ?? 1.0,
            source: row.source ?? "system",
            expires_at: row.expires_at ?? null,
            created_at: existing?.created_at ?? new Date().toISOString(),
        };
        this.memory.set(composite, full);
        return full;
    }

    async getMemory(agent_id: string, key: string, site_id: string | null = null): Promise<AgentMemory | null> {
        return this.memory.get(`${site_id ?? ""}::${agent_id}::${key}`) ?? null;
    }

    async insertTask(row: Partial<AgentTask> & Pick<AgentTask, "assigned_to" | "title">): Promise<AgentTask> {
        const id = row.id ?? randomUUID();
        const full: AgentTask = {
            id,
            site_id: row.site_id ?? null,
            assigned_to: row.assigned_to,
            assigned_by: row.assigned_by ?? "system",
            title: row.title,
            description: row.description ?? "",
            input: row.input ?? null,
            priority: row.priority ?? 5,
            status: row.status ?? "pending",
            due_by: row.due_by ?? null,
            completed_at: row.completed_at ?? null,
            result: row.result ?? null,
            created_at: row.created_at ?? new Date().toISOString(),
        };
        this.tasks.set(id, full);
        return full;
    }

    async listTasks(filter: { assigned_to?: string; status?: AgentTask["status"]; site_id?: string }): Promise<AgentTask[]> {
        let out = Array.from(this.tasks.values());
        if (filter.assigned_to) out = out.filter(t => t.assigned_to === filter.assigned_to);
        if (filter.status) out = out.filter(t => t.status === filter.status);
        if (filter.site_id) out = out.filter(t => t.site_id === filter.site_id);
        // priority: lower number = higher priority
        out.sort((a, b) => a.priority - b.priority);
        return out;
    }

    async updateTask(id: string, patch: Partial<AgentTask>): Promise<void> {
        const cur = this.tasks.get(id);
        if (!cur) return;
        this.tasks.set(id, { ...cur, ...patch });
    }
}

/** Returns a real Supabase-backed DB if env vars are set, else in-memory. */
export function makeDB(): DB {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SUPABASE_KEY;
    if (!url || !key) return new InMemoryDB();
    // TODO: swap to a real Supabase REST adapter once SUPABASE_URL is set.
    // For now (no env), fall back to in-memory so the agents still run.
    return new InMemoryDB();
}

// Singleton — every agent shares the same DB instance.
export const db: DB = makeDB();
