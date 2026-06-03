-- Mesh — initial schema
-- Auth lives in auth.users (managed by Supabase Auth). Everything else is public.
-- RLS is enabled on every table; the policy is membership-of-workspace.
--
-- IMPORTANT: workspace-scoped RLS uses the SECURITY DEFINER helper
-- public.user_workspace_ids(uid) — NEVER inline a subquery against
-- workspace_members from a workspace_members policy (or from another
-- table's policy that also chains through it). Postgres detects the
-- self-reference and errors with 42P17 "infinite recursion detected
-- in policy for relation". SECURITY DEFINER bypasses RLS for the
-- inner lookup so the policy is decidable in one pass.

------------------------------------------------------------------------------
-- profiles ------------------------------------------------------------------
------------------------------------------------------------------------------
create table public.profiles (
  id            uuid references auth.users(id) on delete cascade primary key,
  email         text unique not null,
  display_name  text,
  avatar_url    text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);
alter table public.profiles enable row level security;

create policy "own profile"
  on public.profiles for all
  using (id = auth.uid())
  with check (id = auth.uid());

-- Auto-create a profile row when a Supabase auth user signs up.
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)));
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

------------------------------------------------------------------------------
-- workspaces ----------------------------------------------------------------
------------------------------------------------------------------------------
create table public.workspaces (
  id                     uuid primary key default gen_random_uuid(),
  slug                   text unique not null,
  name                   text not null,
  avatar_url             text,
  owner_id               uuid references public.profiles(id) on delete cascade,
  plan                   text default 'free' check (plan in ('free','pro','team','enterprise')),
  stripe_customer_id     text,
  stripe_subscription_id text,
  broker_url             text,
  broker_token           text,
  created_at             timestamptz default now()
);
alter table public.workspaces enable row level security;

create table public.workspace_members (
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  user_id       uuid references public.profiles(id) on delete cascade,
  role          text default 'member' check (role in ('owner','admin','member','viewer')),
  joined_at     timestamptz default now(),
  primary key (workspace_id, user_id)
);
alter table public.workspace_members enable row level security;

-- Helper: workspaces a user belongs to. SECURITY DEFINER bypasses RLS for
-- the inner select so callers don't trigger recursive policy evaluation.
-- Marked stable so the planner can cache the result inside a single query.
create or replace function public.user_workspace_ids(uid uuid)
returns setof uuid
language sql
security definer
stable
set search_path = public
as $$
  select workspace_id from public.workspace_members where user_id = uid
$$;

-- Helper: roles a user holds in a workspace (used by member-management policy).
create or replace function public.user_workspace_role(uid uuid, wid uuid)
returns text
language sql
security definer
stable
set search_path = public
as $$
  select role from public.workspace_members
  where user_id = uid and workspace_id = wid
  limit 1
$$;

-- Workspaces: members can read; owner can update; any authed user can create.
create policy "members can read their workspaces"
  on public.workspaces for select
  using (id in (select public.user_workspace_ids(auth.uid())));

create policy "owners can update their workspaces"
  on public.workspaces for update
  using (owner_id = auth.uid());

create policy "any authed user can create a workspace"
  on public.workspaces for insert
  with check (auth.uid() is not null and owner_id = auth.uid());

-- Workspace members: each user can always see their own row (no recursion).
-- For seeing OTHER members, the SECURITY DEFINER function is what unbreaks it.
create policy "see own membership"
  on public.workspace_members for select
  using (user_id = auth.uid());

create policy "see co-members"
  on public.workspace_members for select
  using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create policy "owners and admins can manage members"
  on public.workspace_members for all
  using (
    public.user_workspace_role(auth.uid(), workspace_id) in ('owner','admin')
  );

------------------------------------------------------------------------------
-- invites -------------------------------------------------------------------
------------------------------------------------------------------------------
create table public.invites (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  token         text unique not null,
  created_by    uuid references public.profiles(id),
  used_by       uuid references public.profiles(id),
  max_uses      int default 1,
  use_count     int default 0,
  expires_at    timestamptz,
  created_at    timestamptz default now()
);
alter table public.invites enable row level security;

create policy "workspace members can read invites"
  on public.invites for select
  using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create policy "workspace members can create invites"
  on public.invites for insert
  with check (
    public.user_workspace_role(auth.uid(), workspace_id) in ('owner','admin','member')
  );

------------------------------------------------------------------------------
-- instances -----------------------------------------------------------------
------------------------------------------------------------------------------
create table public.instances (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  broker_id     text not null,
  display_name  text not null,
  color         text default '#C9A84C',
  capabilities  text[] default '{}',
  owner_id      uuid references public.profiles(id),
  last_seen     timestamptz,
  created_at    timestamptz default now(),
  unique (workspace_id, broker_id)
);
alter table public.instances enable row level security;

create policy "workspace_member_all" on public.instances
  for all using (workspace_id in (select public.user_workspace_ids(auth.uid())));

------------------------------------------------------------------------------
-- channels / messages / tasks / memory / flows / approvals -----------------
------------------------------------------------------------------------------
create table public.channels (
  id                  uuid primary key default gen_random_uuid(),
  workspace_id        uuid references public.workspaces(id) on delete cascade,
  broker_channel_id   text,
  name                text not null,
  description         text,
  member_instance_ids text[] default '{}',
  created_by          uuid references public.profiles(id),
  created_at          timestamptz default now()
);
alter table public.channels enable row level security;
create policy "workspace_member_all" on public.channels
  for all using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create table public.messages (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  broker_msg_id text,
  from_id       text,
  to_id         text,
  channel_id    uuid references public.channels(id) on delete set null,
  text          text,
  msg_type      text default 'message',
  metadata      jsonb,
  created_at    timestamptz default now()
);
create index messages_workspace_created on public.messages(workspace_id, created_at desc);
create index messages_channel on public.messages(channel_id, created_at desc);
alter table public.messages enable row level security;
create policy "workspace_member_all" on public.messages
  for all using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create table public.tasks (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  title         text not null,
  description   text,
  assignee_id   text,
  created_by    uuid references public.profiles(id),
  status        text default 'backlog' check (status in ('backlog','active','review','done','blocked')),
  priority      text default 'medium' check (priority in ('low','medium','high','critical')),
  deps          text[] default '{}',
  progress      int default 0,
  due_at        timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz default now()
);
alter table public.tasks enable row level security;
create policy "workspace_member_all" on public.tasks
  for all using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create table public.memory (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  key           text not null,
  value         text,
  mem_type      text default 'config' check (mem_type in ('contract','config','design','decision','error','pattern')),
  author_id     text,
  version       int default 1,
  locked_by     text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now(),
  unique(workspace_id, key)
);
alter table public.memory enable row level security;
create policy "workspace_member_all" on public.memory
  for all using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create table public.flows (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  name          text not null,
  trigger_desc  text,
  action_desc   text,
  active        boolean default true,
  fired_count   int default 0,
  last_fired    timestamptz,
  created_by    uuid references public.profiles(id),
  created_at    timestamptz default now()
);
alter table public.flows enable row level security;
create policy "workspace_member_all" on public.flows
  for all using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create table public.approvals (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  agent_id      text,
  action        text not null,
  risk          text default 'low' check (risk in ('low','medium','high')),
  detail        text,
  status        text default 'pending' check (status in ('pending','approved','rejected')),
  decided_by    uuid references public.profiles(id),
  decided_at    timestamptz,
  created_at    timestamptz default now()
);
alter table public.approvals enable row level security;
create policy "workspace_member_all" on public.approvals
  for all using (workspace_id in (select public.user_workspace_ids(auth.uid())));

------------------------------------------------------------------------------
-- api_keys / audit_log / spend ---------------------------------------------
------------------------------------------------------------------------------
create table public.api_keys (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  name          text not null,
  key_hash      text not null,        -- bcrypt hash of the full key
  key_prefix    text not null,        -- mesh_live_xxxx for display
  last_used     timestamptz,
  created_by    uuid references public.profiles(id),
  created_at    timestamptz default now()
);
alter table public.api_keys enable row level security;
create policy "workspace_admin_all" on public.api_keys
  for all using (
    public.user_workspace_role(auth.uid(), workspace_id) in ('owner','admin')
  );

create table public.audit_log (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  actor_id      uuid references public.profiles(id),
  actor_type    text default 'user' check (actor_type in ('user','agent','system')),
  event         text not null,
  detail        jsonb,
  ip_address    inet,
  created_at    timestamptz default now()
);
create index audit_workspace_created on public.audit_log(workspace_id, created_at desc);
alter table public.audit_log enable row level security;
create policy "workspace_member_read" on public.audit_log
  for select using (workspace_id in (select public.user_workspace_ids(auth.uid())));

create table public.spend (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid references public.workspaces(id) on delete cascade,
  date          date not null,
  amount_usd    numeric(10,4) default 0,
  turn_count    int default 0,
  updated_at    timestamptz default now(),
  unique(workspace_id, date)
);
alter table public.spend enable row level security;
create policy "workspace_member_read" on public.spend
  for select using (workspace_id in (select public.user_workspace_ids(auth.uid())));
