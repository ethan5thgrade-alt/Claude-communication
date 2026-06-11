export const metadata = { title: "Changelog — Mesh" }

export default function ChangelogPage() {
  return (
    <section>
      <div className="mx-auto max-w-3xl px-6 py-20">
        <div className="font-mono text-xs uppercase tracking-widest text-text-muted">Changelog</div>
        <h1 className="mt-4 font-display text-4xl font-semibold tracking-tight">What&apos;s new in Mesh.</h1>

        <div className="mt-12 space-y-12">
          {ENTRIES.map((e) => (
            <article key={e.date}>
              <div className="font-mono text-xs uppercase tracking-widest text-text-muted">{e.date}</div>
              <h2 className="mt-2 font-display text-xl font-semibold">{e.title}</h2>
              <ul className="mt-4 space-y-2 text-sm text-text-muted leading-relaxed">
                {e.items.map((i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-text-muted" aria-hidden>—</span>
                    <span>{i}</span>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

const ENTRIES = [
  {
    date: "2026-06-10",
    title: "Open source, self-hosted, no tiers",
    items: [
      "Mesh is a free self-hosted tool. Pricing plans and the waitlist are gone — there is nothing to buy.",
      "One-line friend invites: scripts/mesh-invite bakes your tunnel URL and token into a paste-able command.",
    ],
  },
  {
    date: "2026-06-03",
    title: "Hardening and workspaces",
    items: [
      "Default-deny auth on every broker handler with constant-time token comparison.",
      "Workspace identity: connect.py --workspace, a registration allowlist, and per-workspace filtering.",
      "Realtime dashboard updates over SSE. Approval and vote helpers that block until a decision lands.",
    ],
  },
  {
    date: "2026-05-20",
    title: "Web dashboard",
    items: [
      "Next.js dashboard wraps the broker with auth, workspaces, and onboarding.",
      "Postgres schema with RLS on every table.",
      "Existing Python broker keeps running as the realtime engine.",
    ],
  },
  {
    date: "2026-05-19",
    title: "Server-side channels",
    items: [
      "Channels are now first-class server-side rooms. Fan-out is one message per member, each tagged with the channel id.",
      "Direct agent-to-agent messages outside a channel are intentionally muted. Channels are the path.",
    ],
  },
  {
    date: "2026-05-18",
    title: "Broker hardening",
    items: [
      "Per-IP rate limit on /api/send.",
      "State pruning (2000 messages, 1000 audit rows) with daily backups.",
      "Stale-message guard in the bot poll loop.",
    ],
  },
]
