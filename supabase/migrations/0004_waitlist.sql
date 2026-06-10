-- 0004 — Waitlist for demand probe
-- Simple email collection for evaluating market signal before full SaaS investment.

create table public.waitlist (
  id            uuid primary key default gen_random_uuid(),
  email         text unique not null,
  source        text default 'landing' check (source in ('landing', 'demo', 'community')),
  subscribed_at timestamptz default now(),
  converted_at  timestamptz,
  notes         text
);

alter table public.waitlist enable row level security;

-- Permissive INSERT: anyone can add an email. SELECT/UPDATE/DELETE restricted to
-- authenticated users (for admin dashboard). The API route validates and limits
-- submissions (no spam protection here, handled at application layer).
create policy "anon insert for waitlist"
  on public.waitlist for insert
  with check (true);
