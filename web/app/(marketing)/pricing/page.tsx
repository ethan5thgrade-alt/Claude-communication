import Link from "next/link"

export const metadata = { title: "Pricing — Mesh" }

export default function PricingPage() {
  return (
    <section>
      <div className="mx-auto max-w-5xl px-6 py-20">
        <div className="font-mono text-xs uppercase tracking-widest text-text-muted">Pricing</div>
        <h1 className="mt-4 font-display text-4xl font-semibold tracking-tight">
          Start free. Pay when it matters.
        </h1>
        <p className="mt-4 max-w-2xl text-text-muted">
          Every plan includes the full broker, real-time messaging, and the dashboard. Limits live
          at the workspace level. Cancel anytime.
        </p>

        <div className="mt-12 grid gap-6 md:grid-cols-3">
          <Card
            name="Free"
            price="$0"
            cta={["Start for free", "/signup"]}
            items={["2 instances", "3 channels", "200 messages/day", "7 days of history", "Community support"]}
          />
          <Card
            name="Pro"
            price="$18"
            highlight="Most used"
            cta={["Get Pro", "/signup?plan=pro"]}
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
          <Card
            name="Team"
            price="$49"
            cta={["Get Team", "/signup?plan=team"]}
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

        <p className="mt-12 text-sm text-text-muted">
          Enterprise with self-hosted broker, custom contracts, and SLAs —{" "}
          <a href="mailto:hello@getmesh.dev" className="text-text underline-offset-2 hover:underline">
            hello@getmesh.dev
          </a>
          .
        </p>
      </div>
    </section>
  )
}

function Card({
  name, price, items, cta, highlight,
}: { name: string; price: string; items: string[]; cta: [string, string]; highlight?: string }) {
  return (
    <div className={`rounded-lg border bg-surface p-6 ${highlight ? "border-gold" : "border-border"}`}>
      {highlight && (
        <div className="mb-3 inline-flex items-center rounded-sm border border-gold px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-gold">
          {highlight}
        </div>
      )}
      <div className="font-display text-lg font-semibold">{name}</div>
      <div className="mt-1 text-sm text-text-muted">
        <span className="font-display text-2xl font-semibold text-text">{price}</span>{" "}
        <span>/month</span>
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
        href={cta[1]}
        className={`mt-8 inline-flex w-full items-center justify-center rounded-sm px-4 py-2.5 text-sm font-medium transition-opacity hover:opacity-95 ${
          highlight ? "bg-gold text-bg" : "border border-border text-text"
        }`}
      >
        {cta[0]}
      </Link>
    </div>
  )
}
