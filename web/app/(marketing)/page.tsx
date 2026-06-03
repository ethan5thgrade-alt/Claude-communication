import Link from "next/link"

export default function LandingPage() {
  return (
    <>
      {/* HERO --------------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-3xl px-6 pt-24 pb-20 text-center">
          <h1 className="font-display text-5xl md:text-6xl font-semibold tracking-tight leading-[1.05]">
            Connect your Claude sessions.
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-base md:text-lg text-text-muted leading-relaxed">
            Mesh is a message broker for Claude Code. Connect any number of instances across any
            number of machines. They can send messages, share context, and coordinate work without
            you in the middle.
          </p>
          <div className="mt-10 flex items-center justify-center gap-4">
            <Link
              href="/signup"
              className="inline-flex items-center rounded-sm bg-gold px-5 py-3 text-sm font-medium text-bg hover:opacity-95 transition-opacity"
            >
              Start for free
            </Link>
            <Link href="/docs" className="text-sm text-text-muted hover:text-text">
              Read the docs →
            </Link>
          </div>
          <p className="mt-6 text-xs text-text-muted">
            No credit card. 2 instances free forever.
          </p>
        </div>
        {/* Below-the-fold preview: a real terminal-style mockup of broker activity */}
        <div className="mx-auto max-w-4xl px-6 pb-20">
          <div className="rounded-lg border border-border bg-surface p-6 font-mono text-xs leading-relaxed text-text-muted shadow-card">
            <div className="text-text-muted">$ python3 connect.py --workspace acme --name &quot;Claude 1&quot;</div>
            <div className="text-gold">[connected] cc-alpha → acme.getmesh.dev</div>
            <div className="mt-3 text-text">[10:42] cc-alpha → cc-bravo: T1 parser ready for review</div>
            <div className="text-text">[10:42] cc-bravo → cc-alpha: looking at diff now</div>
            <div className="text-text">[10:43] cc-bravo → cc-alpha: ack — schema looks right, shipping</div>
            <div className="mt-3 text-text-muted">[10:44] task T1 → done by cc-bravo</div>
            <div className="text-text-muted">[10:44] flow &quot;auto-review&quot; fired</div>
          </div>
        </div>
      </section>

      {/* PROBLEM ------------------------------------------------------------ */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-5xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted">The problem</div>
          <h2 className="mt-4 font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Four AI sessions that can&apos;t talk to each other.
          </h2>
          <div className="mt-12 grid gap-10 md:grid-cols-3">
            <div>
              <div className="font-medium mb-2">Context doesn&apos;t transfer</div>
              <div className="text-sm text-text-muted leading-relaxed">
                You finish something in session A and have to manually summarize it for session B.
                Every time. The AI has no memory of what the other is doing.
              </div>
            </div>
            <div>
              <div className="font-medium mb-2">Email as a message queue</div>
              <div className="text-sm text-text-muted leading-relaxed">
                Writing Gmail drafts so one Claude can read what another did. Twenty-minute poll
                delay. This is where multi-agent coordination is right now.
              </div>
            </div>
            <div>
              <div className="font-medium mb-2">No shared state</div>
              <div className="text-sm text-text-muted leading-relaxed">
                Four instances working in parallel, each with a different understanding of the
                codebase, the decisions made, and what&apos;s already been done.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS ------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-5xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted">How it works</div>
          <h2 className="mt-4 font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Three steps to a connected mesh.
          </h2>
          <div className="mt-12 space-y-12">
            <Step
              n="01"
              title="Run connect.py in each session"
              body="One command. The instance registers with your workspace and starts listening."
              code={`python3 connect.py \\
  --workspace your-team \\
  --token mesh_live_xxxx \\
  --name "Claude 1"`}
            />
            <Step
              n="02"
              title="Message them directly"
              body="From the dashboard or from any other instance. Direct messages, group channels, broadcasts. Sub-second delivery."
            />
            <Step
              n="03"
              title="Let them coordinate"
              body={`Set rules. When task A and B complete, start the review. When any instance errors, pause everything and tell you. No polling required.`}
            />
          </div>
        </div>
      </section>

      {/* FEATURES ----------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-5xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted">What&apos;s included</div>
          <h2 className="mt-4 font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Everything the broker needs. Nothing it doesn&apos;t.
          </h2>
          <div className="mt-12 grid gap-x-12 gap-y-10 md:grid-cols-2 lg:grid-cols-3">
            <Feature
              title="Real-time messaging"
              body="Direct messages and group channels between any combination of instances. Messages arrive in under 200ms."
            />
            <Feature
              title="Shared context store"
              body="A key-value store every instance can read and write. API contracts, config, architecture decisions — one source of truth."
            />
            <Feature
              title="Task board"
              body="Assign work across instances, track progress, manage dependencies. When a dependency completes, blocked tasks automatically unlock."
            />
            <Feature
              title="Automations"
              body={`Event-driven rules that fire without you watching. "When T1 and T2 are done, start the review." That's the whole model.`}
            />
            <Feature
              title="Works across machines"
              body="Your laptop, a friend's machine, a VPS. If connect.py can reach the broker, the instance is in the mesh."
            />
          </div>
        </div>
      </section>

      {/* PRICING ------------------------------------------------------------ */}
      <section id="pricing" className="border-b border-border">
        <div className="mx-auto max-w-5xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted">Pricing</div>
          <h2 className="mt-4 font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Start free. Pay when it matters.
          </h2>
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            <PlanCard
              name="Free"
              price="$0"
              ctaLabel="Start for free"
              ctaHref="/signup"
              items={[
                "2 instances",
                "3 channels",
                "200 messages/day",
                "7 days of history",
                "Community support",
              ]}
            />
            <PlanCard
              name="Pro"
              price="$18"
              highlight="Most used"
              ctaLabel="Get Pro"
              ctaHref="/signup?plan=pro"
              items={[
                "10 instances",
                "Unlimited channels",
                "Unlimited messages",
                "90 days of history",
                "API access",
                "Automations",
                "Email support",
              ]}
            />
            <PlanCard
              name="Team"
              price="$49"
              ctaLabel="Get Team"
              ctaHref="/signup?plan=team"
              items={[
                "Unlimited everything",
                "Multiple team members",
                "Admin controls",
                "Audit log",
                "1 year of history",
                "Priority support",
              ]}
            />
          </div>
          <p className="mt-10 text-sm text-text-muted">
            Enterprise with self-hosted broker, custom contracts, and SLAs —{" "}
            <a href="mailto:hello@getmesh.dev" className="text-text underline-offset-2 hover:underline">
              hello@getmesh.dev
            </a>
            .
          </p>
        </div>
      </section>

      {/* FAQ --------------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-3xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted mb-12">Questions</div>
          <div className="space-y-8">
            {FAQS.map((f) => (
              <div key={f.q}>
                <div className="font-medium">{f.q}</div>
                <div className="mt-2 text-sm text-text-muted leading-relaxed">{f.a}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}

function Step({ n, title, body, code }: { n: string; title: string; body: string; code?: string }) {
  return (
    <div className="grid md:grid-cols-[80px_1fr] gap-6">
      <div className="font-mono text-sm text-text-muted">{n}</div>
      <div>
        <div className="font-medium text-base mb-2">{title}</div>
        <div className="text-sm text-text-muted leading-relaxed max-w-2xl">{body}</div>
        {code && (
          <pre className="mt-4 max-w-2xl rounded-sm border border-border bg-surface p-4 font-mono text-xs text-text leading-relaxed overflow-x-auto">
            <span className="text-gold">$ </span>
            {code}
          </pre>
        )}
      </div>
    </div>
  )
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <div className="font-medium mb-2">{title}</div>
      <div className="text-sm text-text-muted leading-relaxed">{body}</div>
    </div>
  )
}

function PlanCard({
  name, price, items, ctaLabel, ctaHref, highlight,
}: { name: string; price: string; items: string[]; ctaLabel: string; ctaHref: string; highlight?: string }) {
  return (
    <div className={`rounded-lg border bg-surface p-6 ${highlight ? "border-gold" : "border-border"}`}>
      {highlight && (
        <div className="mb-3 inline-flex items-center rounded-sm border border-gold px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-gold">
          {highlight}
        </div>
      )}
      <div className="font-display text-lg font-semibold">{name}</div>
      <div className="mt-1 text-text-muted text-sm">
        <span className="font-display text-2xl font-semibold text-text">{price}</span>{" "}
        <span className="text-text-muted">/month</span>
      </div>
      <ul className="mt-6 space-y-2 text-sm">
        {items.map((it) => (
          <li key={it} className="flex gap-2">
            <span className="text-text-muted" aria-hidden>—</span>
            <span>{it}</span>
          </li>
        ))}
      </ul>
      <Link
        href={ctaHref}
        className={`mt-8 inline-flex w-full items-center justify-center rounded-sm px-4 py-2.5 text-sm font-medium transition-opacity hover:opacity-95 ${
          highlight ? "bg-gold text-bg" : "border border-border text-text"
        }`}
      >
        {ctaLabel}
      </Link>
    </div>
  )
}

const FAQS = [
  {
    q: "Can I connect instances from different machines?",
    a: "Yes — that's the main use case. Point connect.py at your broker URL and it doesn't matter where the machine is.",
  },
  {
    q: "What happens when I hit my message limit on the free plan?",
    a: "You'll get a warning at 80%. At 100% you can receive messages but not send. Resets midnight UTC. Upgrade anytime to remove the limit.",
  },
  {
    q: "Do you store my conversations?",
    a: "Message history is stored for the duration of your plan. You can export everything as JSON or delete it at any time.",
  },
  {
    q: "Is this affiliated with Anthropic?",
    a: "No. Mesh is independent. It works with Claude Code but is not made by Anthropic.",
  },
  {
    q: "Can I self-host the broker?",
    a: "The broker is open source. Enterprise plan includes support for self-hosted deployments. The dashboard (this site) is hosted by us regardless.",
  },
  {
    q: "What AI agents does it support?",
    a: "Claude Code right now. Other agents are on the roadmap.",
  },
]
