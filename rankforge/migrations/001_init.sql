-- RankForge core infrastructure tables.
-- Run against a Supabase project (or any Postgres 14+).
-- Idempotent: safe to re-run.

create extension if not exists "uuid-ossp";

create table if not exists agent_runs (
    id uuid primary key default gen_random_uuid(),
    agent_id text not null,
    agent_version text,
    site_id uuid,
    status text not null default 'queued',          -- queued|running|success|failed|skipped|retrying
    attempt int not null default 1,
    input jsonb,
    output jsonb,
    error text,
    duration_ms int,
    tokens_used int,
    api_calls jsonb,                                 -- {openai: N, dataforseo: N, bing: N}
    triggered_by text,                               -- agent_id | 'user' | 'cron' | 'system'
    triggered_agents text[],
    created_at timestamptz not null default now(),
    completed_at timestamptz
);
create index if not exists agent_runs_agent_status_idx on agent_runs (agent_id, status, created_at desc);
create index if not exists agent_runs_site_idx on agent_runs (site_id, created_at desc);

create table if not exists agent_messages (
    id uuid primary key default gen_random_uuid(),
    from_agent text,
    to_agent text,                                   -- specific agent id or 'broadcast'
    site_id uuid,
    message_type text,                               -- task|status|data|error|query|response
    payload jsonb,
    priority int not null default 5,                 -- 1 (highest) to 10 (lowest)
    delivered boolean not null default false,
    read_at timestamptz,
    created_at timestamptz not null default now()
);
create index if not exists agent_messages_to_undelivered_idx on agent_messages (to_agent) where delivered = false;
create index if not exists agent_messages_site_idx on agent_messages (site_id, created_at desc);

create table if not exists agent_memory (
    id uuid primary key default gen_random_uuid(),
    site_id uuid,
    agent_id text,
    memory_type text,                                -- learned|context|preference|pattern|error
    key text,
    value jsonb,
    confidence float,                                -- 0.0-1.0
    source text,                                     -- which agent_run produced this
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    unique (site_id, agent_id, key)
);
create index if not exists agent_memory_lookup_idx on agent_memory (site_id, agent_id, key);

create table if not exists agent_tasks (
    id uuid primary key default gen_random_uuid(),
    site_id uuid,
    assigned_to text,                                -- agent_id
    assigned_by text,                                -- agent_id or 'user'
    title text,
    description text,
    input jsonb,
    priority int not null default 5,
    status text not null default 'pending',          -- pending|claimed|running|done|failed|cancelled
    due_by timestamptz,
    completed_at timestamptz,
    result jsonb,
    created_at timestamptz not null default now()
);
create index if not exists agent_tasks_assigned_pending_idx on agent_tasks (assigned_to, status, priority);

create table if not exists agent_learning (
    id uuid primary key default gen_random_uuid(),
    agent_id text not null,
    site_id uuid,
    pattern_type text,                               -- success|failure|optimization|correlation
    pattern text,
    evidence jsonb,
    applied boolean not null default false,
    impact_measured float,
    created_at timestamptz not null default now()
);
create index if not exists agent_learning_agent_idx on agent_learning (agent_id, created_at desc);

-- Site registry: the unit of work for the whole RankForge system.
-- Group 1 agents read this to find work; later groups update it.
create table if not exists sites (
    id uuid primary key default gen_random_uuid(),
    url text unique not null,
    plan_tier text not null default 'free',          -- free|starter|pro|agency
    state text not null default 'new',               -- see Site State Machine (agent 002)
    state_updated_at timestamptz not null default now(),
    paused boolean not null default false,
    timezone text default 'UTC',
    urgency int not null default 5,                  -- 1-10, higher = sooner
    last_run_at timestamptz,
    config jsonb,
    created_at timestamptz not null default now()
);
create index if not exists sites_state_idx on sites (state, paused, urgency desc, last_run_at);

-- State-machine history (one row per transition).
create table if not exists site_state_history (
    id bigserial primary key,
    site_id uuid not null references sites (id) on delete cascade,
    from_state text,
    to_state text not null,
    reason text,
    changed_at timestamptz not null default now()
);
create index if not exists site_state_history_site_idx on site_state_history (site_id, changed_at desc);
