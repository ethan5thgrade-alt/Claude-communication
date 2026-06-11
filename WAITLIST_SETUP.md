# Waitlist Setup for Demand Probe

> **STATUS (2026-06-10): LIVE.** Production URL: **https://mesh-web-nine.vercel.app**
> - Migration 0004 applied to Supabase project `uaxwcewqvpifahjltaef` (was never run before).
> - Vercel project `mesh-web` linked from `web/`, env vars set (production), deployed, e2e-tested.
> - Route bug fixed: insert no longer uses `.select()` (anon RLS allows INSERT only).
> - **BLOCKER: we do NOT own getmesh.dev** — it belongs to "Mesh — AI-Forward Consultancy"
>   (DigitalOcean-hosted). Step 4 below is impossible as written. Either buy a different
>   domain (spend — needs explicit OK) or launch the probe on the vercel.app URL.
> - Supabase free tier auto-pauses on inactivity; if signups 500, check project status first.

## What was built

- **Supabase table** (`0004_waitlist.sql`): Collects emails with source tracking
- **API route** (`/api/waitlist`): Validates and inserts emails, handles duplicates
- **WaitlistForm component**: Email input, validation, loading state, error messages
- **Landing page**: Hero CTA replaced with waitlist form, new dedicated waitlist section

## Before deploying to Vercel

### 1. Apply the Supabase migration

Run migration 0004 against your Supabase project:

```sql
-- Option A: Via Supabase dashboard (SQL editor)
-- Copy the entire contents of supabase/migrations/0004_waitlist.sql
-- and run it in the Supabase SQL editor at https://app.supabase.com

-- Option B: Via Supabase CLI (if installed)
supabase migration up
```

**Verify**: In Supabase dashboard → Tables, you should see a new `waitlist` table with:
- `id` (uuid, primary key)
- `email` (text, unique, not null)
- `source` (text, default 'landing')
- `subscribed_at` (timestamp, auto)
- `converted_at` (timestamp, nullable)
- `notes` (text, nullable)

### 2. Test locally (optional)

```bash
cd ~/code/Claude-communication/web
npm install
npm run dev

# In another terminal, test the API:
curl -X POST http://localhost:3000/api/waitlist \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com"}'
```

Expected response:
```json
{
  "success": true,
  "data": {
    "id": "...",
    "email": "test@example.com",
    "source": "landing",
    "subscribed_at": "..."
  }
}
```

### 3. Deploy to Vercel

**Link the repo to Vercel** (if not already):

```bash
cd ~/code/Claude-communication/web
vercel link  # Follow prompts
```

**Set environment variables**:

```bash
vercel env add NEXT_PUBLIC_SUPABASE_URL
# Paste: https://uaxwcewqvpifahjltaef.supabase.co

vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY
# Paste: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVheHdjZXdxdnBpZmFoamx0YWVmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA0OTExMTQsImV4cCI6MjA5NjA2NzExNH0.LapxGsDpMwxpx1Rjpu3GQ0M89RWUuZRqyGF9P_ksB_A
```

**Deploy**:

```bash
git push origin main
# Auto-deploys if Vercel is linked, or:
vercel deploy --prod
```

### 4. Point domain to Vercel

Once deployed, get your Vercel URL (e.g., `mesh-web-xyz.vercel.app`) and:

1. Update DNS for `getmesh.dev` to point to Vercel
2. Add `getmesh.dev` as a custom domain in Vercel project settings
3. Vercel will issue an SSL cert automatically

## Monitoring signups

### Via Supabase dashboard

```sql
-- Count signups
SELECT COUNT(*) as total_signups, source, 
  DATE_TRUNC('day', subscribed_at) as day
FROM public.waitlist
GROUP BY source, day
ORDER BY day DESC;

-- Export as JSON
SELECT * FROM public.waitlist ORDER BY subscribed_at DESC;
```

### Via CLI (manual check)

```bash
# Pull the latest state
supabase db pull

# Or query directly
psql "postgres://postgres:password@db.supabase.co/postgres" \
  -c "SELECT email, source, subscribed_at FROM public.waitlist ORDER BY subscribed_at DESC LIMIT 10;"
```

## Kill gate (2-week evaluation)

**Success criteria**:
- ~25 signups, OR
- ~10 "I'd pay" responses (track manually in notes field)

**Failure criteria** (freeze Mesh):
- <10 signups after 2 weeks, AND
- No "I'd pay" signals

**If success**: Launch full onboarding, enable signup, move to Phase 2.  
**If failure**: Set Mesh to maintenance mode, redirect focus to OPTFINDER / Lead-Agent.

## Posting to communities

Once deployed and waitlist is live:

1. **r/ClaudeAI**: "We built a message broker for multi-Claude-Code coordination"
2. **r/LocalLLaMA**: "Multi-agent orchestration for local AI"
3. **Show HN**: "Mesh — connect your Claude sessions" (technical angle)

Include:
- 60-90s demo video (optional but helpful)
- `getmesh.dev` link
- "Early access — 25 spots available"

## Files changed

- `supabase/migrations/0004_waitlist.sql` — New table + RLS policy
- `web/components/WaitlistForm.tsx` — Client-side form component
- `web/app/api/waitlist/route.ts` — API endpoint
- `web/app/(marketing)/page.tsx` — Hero CTA + waitlist section

All committed in `6a97ad6`.
