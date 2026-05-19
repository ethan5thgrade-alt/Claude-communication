// Shared types for the RankForge agent system.
//
// Every agent in the 300-agent spec extends AgentBase (see ./AgentBase.ts) and
// speaks these shapes. Keep this file pure-types — no runtime deps.

export type SiteState =
    | "new"
    | "crawling"
    | "analyzing"
    | "keyword_research"
    | "content_planning"
    | "generating"
    | "publishing"
    | "live"
    | "monitoring"
    | "optimizing";

export type PlanTier = "free" | "starter" | "pro" | "agency";

export interface Site {
    id: string;
    url: string;
    plan_tier: PlanTier;
    state: SiteState;
    state_updated_at: string;
    paused: boolean;
    timezone: string;
    urgency: number;
    last_run_at: string | null;
    config: Record<string, unknown> | null;
    created_at: string;
}

export interface AgentInput {
    site_id?: string;
    site?: Site;
    payload?: unknown;
    triggered_by?: string;
    [key: string]: unknown;
}

export interface AgentOutput {
    ok: boolean;
    data?: unknown;
    error?: string;
    artifacts?: Record<string, unknown>;
}

export interface AgentTrigger {
    agent_id: string;
    input: AgentInput;
    priority?: number;
}

export type RunStatus = "queued" | "running" | "success" | "failed" | "skipped" | "retrying";

export interface AgentRun {
    id: string;
    agent_id: string;
    agent_version: string;
    site_id: string | null;
    status: RunStatus;
    attempt: number;
    input: AgentInput | null;
    output: AgentOutput | null;
    error: string | null;
    duration_ms: number | null;
    tokens_used: number | null;
    api_calls: Record<string, number> | null;
    triggered_by: string;
    triggered_agents: string[];
    created_at: string;
    completed_at: string | null;
}

export type MessageType = "task" | "status" | "data" | "error" | "query" | "response";

export interface AgentMessage {
    id: string;
    from_agent: string;
    to_agent: string;       // specific id, or "broadcast"
    site_id: string | null;
    message_type: MessageType;
    payload: unknown;
    priority: number;
    delivered: boolean;
    read_at: string | null;
    created_at: string;
}

export type MemoryType = "learned" | "context" | "preference" | "pattern" | "error";

export interface AgentMemory {
    id: string;
    site_id: string | null;
    agent_id: string;
    memory_type: MemoryType;
    key: string;
    value: unknown;
    confidence: number;
    source: string;          // agent_run id
    expires_at: string | null;
    created_at: string;
}

export type TaskStatus = "pending" | "claimed" | "running" | "done" | "failed" | "cancelled";

export interface AgentTask {
    id: string;
    site_id: string | null;
    assigned_to: string;
    assigned_by: string;
    title: string;
    description: string;
    input: AgentInput | null;
    priority: number;
    status: TaskStatus;
    due_by: string | null;
    completed_at: string | null;
    result: AgentOutput | null;
    created_at: string;
}

export type ErrorClass = "transient" | "permanent" | "rate_limit" | "auth" | "data" | "unknown";

export interface LogEvent {
    level: "debug" | "info" | "warn" | "error";
    agent_id: string;
    site_id?: string | null;
    message: string;
    data?: Record<string, unknown>;
    ts: string;
}
