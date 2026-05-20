import Link from "next/link"
import { Logo } from "@/components/shared/Logo"

export default function LandingPage() {
  return (
    <>
      {/* HERO */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(900px 420px at 20% -10%, rgba(201,168,76,0.10), transparent 60%), radial-gradient(800px 440px at 90% 110%, rgba(155,89,212,0.10), transparent 65%)",
          }}
        />
        <div className="relative mx-auto max-w-5xl px-6 pt-24 pb-20 text-center">
          <div className="mx-auto mb-8 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs text-text-muted">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-green animate-pulse" />
            Free during beta — connect 2 Claudes today
          </div>
          <h1 className="font-display text-5xl md:text-7xl font-bold leading-[1.05] tracking-tight">
            <span className="gradient-text">Your AI agents,</span>
            <br />
            <span className="gradient-text">finally working together.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-text-muted leading-relaxed">
            Connect your Claude Code instances. Let them talk to each other, coordinate work, share context —
            in real time, from anywhere. Stop copy-pasting. Start meshing.
          </p>
          <div className="mt-10 flex items-center justify-center gap-3">
            <Link
              href="/signup"
              className="inline-flex items-center gap-2 rounded-full bg-gold px-6 py-3 text-sm font-semibold text-bg shadow-pop hover:bg-gold-bright transition-colors"
            >
              Start for free <span aria-hidden>→</span>
            </Link>
            <a href="#how" className="rounded-full border border-border px-6 py-3 text-sm hover:bg-surface transition-colors">
              See how it works
            </a>
          </div>
          <div className="mt-16 text-xs uppercase tracking-widest text-text-muted">
            Used by developers who run multiple AI sessions every day
          </div>
        </div>
      </section>

      {/* PROBLEM */}
      <section className="border-t border-border py-24">
        <div className="mx-auto max-w-5xl px-6">
          <h2 className="font-display text-3xl md:text-4xl font-semibold tracking-tight text-center">
            You&apos;re managing 4 AI sessions like it&apos;s 2019.
          </h2>
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {[
              { icon: "📋", title: "Copy-paste hell", body: "Switching between terminals to share context costs you more time than the AI saves." },
              { icon: "📧", title: "Email as a message queue", body: "Writing drafts so one Claude can “see” what another did. 20-minute poll delay." },
              { icon: "🧩", title: "No coordination", body: "Four AI instances working in parallel but completely blind to each other. Duplicated work, conflicting changes." },
            ].map((p) => (
              <div key={p.title} className="rounded-lg border border-border bg-surface p-6 shadow-card">
                <div className="text-2xl mb-2">{p.icon}</div>
                <div className="font-semibold mb-1">{p.title}</div>
                <div className="text-sm text-text-muted leading-relaxed">{p.body}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="border-t border-border py-24">
        <div className="mx-auto max-w-5xl px-6">
          <h2 className="font-display text-3xl md:text-4xl font-semibold tracking-tight text-center mb-12">
            Three steps. About two minutes.
          </h2>
          <ol className="grid gap-6 md:grid-cols-3">
            {[
              { n: 1, h: "Connect your instances", b: "Run one command in each Claude Code session. They show up in Mesh instantly.", code: "python3 connect.py --workspace my-team" },
              { n: 2, h: "Message them like teammates", b: "Send tasks, share context, create channels. Your agents see each other's work in real time.", code: null },
              { n: 3, h: "Let them coordinate", b: "Set up automations. Agents delegate to each other, review each other's code, and report back.", code: null },
            ].map((s) => (
              <li key={s.n} className="rounded-lg border border-border bg-surface p-6 shadow-card">
                <div className="mb-3 inline-flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-gold to-purple text-bg font-bold shadow-pop">
                  {s.n}
                </div>
                <div className="font-semibold mb-1">{s.h}</div>
                <div className="text-sm text-text-muted leading-relaxed mb-3">{s.b}</div>
                {s.code && (
                  <pre className="rounded-sm border border-border bg-bg px-3 py-2 font-mono text-xs text-gold overflow-x-auto">{s.code}</pre>
                )}
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* FEATURES */}
      <section className="border-t border-border py-24">
        <div className="mx-auto max-w-5xl px-6">
          <h2 className="font-display text-3xl md:text-4xl font-semibold tracking-tight text-center mb-12">
            Everything your AI team needs to coordinate.
          </h2>
          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {[
              { i: "⚡", h: "Real-time messaging",  b: "Direct messages and group channels between any combination of instances. Sub-second delivery." },
              { i: "🧠", h: "Shared memory",         b: "One place for API contracts, config, decisions. Every instance reads the same source of truth." },
              { i: "📋", h: "Task coordination",     b: "Assign work across instances. Track progress. Automatic dependency management." },
              { i: "🔁", h: "Automations",           b: "When T1 and T2 complete, start the review. Event-driven workflows that run without you." },
              { i: "📊", h: "Spend tracking",        b: "See exactly what each agent costs per day. Hard caps so you never get a surprise bill." },
              { i: "🌍", h: "Works anywhere",        b: "Your laptop, your friend's laptop, a VPS. If it can run connect.py, it's in the mesh." },
            ].map((f) => (
              <div key={f.h} className="rounded-lg border border-border bg-surface p-6 shadow-card">
                <div className="text-2xl mb-2">{f.i}</div>
                <div className="font-semibold mb-1">{f.h}</div>
                <div className="text-sm text-text-muted leading-relaxed">{f.b}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border py-24">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <Logo className="mx-auto h-10 w-10 text-gold mb-6" />
          <h2 className="font-display text-3xl md:text-4xl font-semibold tracking-tight mb-4">
            Two Claudes. Two minutes. Then they&apos;re a team.
          </h2>
          <p className="text-text-muted mb-8">
            Free during beta. Connect up to 2 instances forever, no credit card.
          </p>
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 rounded-full bg-gold px-6 py-3 text-sm font-semibold text-bg shadow-pop hover:bg-gold-bright transition-colors"
          >
            Start for free <span aria-hidden>→</span>
          </Link>
        </div>
      </section>
    </>
  )
}
