# mesh-web

Next.js 14 product layer for Mesh. The Python broker at `../broker.py` remains
the realtime engine; this app handles auth, workspaces, billing, and the
marketing site.

## Phase 1 (current)

What's implemented:
- `/` landing page with hero / problem / how / features / CTA
- `/signup` `/login` `/verify` with Supabase Auth (email + password)
- Email verification callback at `/api/auth/callback`
- 3-step onboarding: name workspace → connect Claude → invite teammate
- Middleware: unauth users redirect to `/login`, with `?next=` round-trip
- App shell at `/[workspaceSlug]` with sidebar + dashboard placeholder
- Supabase schema (`/supabase/migrations/0001_init.sql`) with RLS on every table

## Local development

```bash
# 1. Create a Supabase project at https://supabase.com and run the migration
#    psql "$DATABASE_URL" < ../supabase/migrations/0001_init.sql
#    (or paste it into the Supabase SQL editor)

# 2. Copy env vars
cp .env.example .env.local
# Fill in NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY
# (Settings → API in your Supabase dashboard)

# 3. Install
npm install

# 4. Run
npm run dev   # localhost:3000
```

## Connecting the broker

In a separate terminal:
```bash
cd ..
python3 broker.py
```

The onboarding "Connect your Claude" step polls `NEXT_PUBLIC_BROKER_HTTP` for
online instances. With the broker on `localhost:8765`, the polling will detect
any `connect.py` session that registers.

## What's next

- Phase 2: Chat page (channels + DMs), Tasks kanban, Memory store
- Phase 3: Invite emails (Resend), Analytics, Spend tracking, Automations
- Phase 4: Stripe billing, API keys, Public `/v1/*` API, Admin panel
- Phase 5: Full landing + pricing + blog + changelog + OG
- Phase 6: Production deployment (Vercel + Hetzner broker)
