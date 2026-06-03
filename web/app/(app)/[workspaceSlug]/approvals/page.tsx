"use client"
import { use, useState } from "react"
import { brokerApprove, brokerPost, useApprovals } from "@/lib/broker/client"
import type { Approval } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

const RISKS: Approval["risk"][] = ["low", "med", "high"]

export default function ApprovalsPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const approvals = useApprovals(workspaceSlug)

  const [action, setAction] = useState("")
  const [risk, setRisk] = useState<Approval["risk"]>("low")
  const [detail, setDetail] = useState("")
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const list = approvals.data?.approvals ?? []
  const pending = list.filter((a) => a.status === "pending")
  const decided = list
    .filter((a) => a.status !== "pending")
    .sort((a, b) =>
      (b.decided_at || b.ts || "").localeCompare(a.decided_at || a.ts || ""),
    )

  async function create() {
    if (!action.trim() || creating) return
    setCreating(true)
    setError(null)
    try {
      await brokerPost(workspaceSlug, "approval", {
        action: action.trim(),
        risk,
        detail: detail.trim() || undefined,
      })
      setAction("")
      setDetail("")
      setRisk("low")
      approvals.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8">
        <h1 className="font-display text-2xl font-semibold tracking-tight">
          Approvals
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          Instances request sign-off before high-risk actions. Decide here; the
          requester is notified.
        </p>
      </header>

      <div className="mb-8 rounded-sm border border-border bg-surface p-4">
        <div className="mb-3 text-xs uppercase tracking-widest text-text-muted">
          Request approval
        </div>
        {error && (
          <div className="mb-2 text-xs text-red-400">Request failed: {error}.</div>
        )}
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <input
              value={action}
              onChange={(e) => setAction(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && create()}
              placeholder="Action to approve, e.g. deploy to production"
              className="flex-1 min-w-[200px] rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
            />
            <select
              value={risk}
              onChange={(e) => setRisk(e.target.value as Approval["risk"])}
              className="rounded-sm border border-border bg-bg px-3 py-2 text-sm focus:outline-none"
            >
              {RISKS.map((r) => (
                <option key={r} value={r}>
                  risk: {r}
                </option>
              ))}
            </select>
            <button
              onClick={create}
              disabled={!action.trim() || creating}
              className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
            >
              {creating ? "Requesting" : "Request"}
            </button>
          </div>
          <textarea
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            placeholder="Detail (optional)"
            rows={2}
            className="w-full resize-y rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
        </div>
      </div>

      <section className="mb-8">
        <div className="mb-2 flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">Pending</h2>
          <span className="text-xs text-text-muted">{pending.length}</span>
        </div>
        {pending.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
            No pending approvals.
          </div>
        ) : (
          <div className="space-y-2">
            {pending.map((a) => (
              <PendingCard
                key={a.id}
                a={a}
                slug={workspaceSlug}
                onDecided={approvals.refetch}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">History</h2>
          <span className="text-xs text-text-muted">{decided.length}</span>
        </div>
        {decided.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
            No decided approvals yet.
          </div>
        ) : (
          <div className="space-y-2">
            {decided.map((a) => (
              <DecidedRow key={a.id} a={a} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function RiskBadge({ risk }: { risk: Approval["risk"] }) {
  const cls =
    risk === "high"
      ? "text-red-400"
      : risk === "med"
        ? "text-gold"
        : "text-text-muted"
  return <span className={cls}>risk: {risk}</span>
}

function PendingCard({
  a,
  slug,
  onDecided,
}: {
  a: Approval
  slug: string
  onDecided: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function respond(approved: boolean) {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await brokerApprove(slug, a.id, approved)
      onDecided()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-sm border border-border bg-surface p-4">
      <div className="flex items-start gap-4">
        <div className="flex-1">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-xs text-text-muted">{a.id}</span>
            <span className="text-sm font-medium">{a.action}</span>
          </div>
          {a.detail && (
            <div className="mt-1 whitespace-pre-wrap break-words text-sm text-text-muted">
              {a.detail}
            </div>
          )}
          <div className="mt-2 flex items-center gap-3 text-xs text-text-muted">
            <RiskBadge risk={a.risk} />
            <span>
              requester: <span className="font-mono text-text">{a.from}</span>
            </span>
            <span>{formatTs(a.ts)}</span>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            onClick={() => respond(true)}
            disabled={busy}
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
          >
            Approve
          </button>
          <button
            onClick={() => respond(false)}
            disabled={busy}
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm font-semibold text-red-400 disabled:opacity-40 hover:bg-surface-2"
          >
            Reject
          </button>
        </div>
      </div>
      {error && (
        <div className="mt-2 text-xs text-red-400">Decision failed: {error}.</div>
      )}
    </div>
  )
}

function DecidedRow({ a }: { a: Approval }) {
  const verdictClass =
    a.status === "approved" ? "text-text" : "text-red-400"
  return (
    <div className="rounded-sm border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-text-muted">{a.id}</span>
          <span className="text-sm font-medium">{a.action}</span>
        </div>
        <span className={`text-xs font-semibold ${verdictClass}`}>
          {a.status}
        </span>
      </div>
      {a.detail && (
        <div className="mt-1 whitespace-pre-wrap break-words text-sm text-text-muted">
          {a.detail}
        </div>
      )}
      <div className="mt-2 flex items-center gap-3 text-xs text-text-muted">
        <RiskBadge risk={a.risk} />
        <span>
          requester: <span className="font-mono text-text">{a.from}</span>
        </span>
        <span>decided: {formatTs(a.decided_at || a.ts)}</span>
      </div>
    </div>
  )
}

function formatTs(iso?: string): string {
  if (!iso) return "—"
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}
