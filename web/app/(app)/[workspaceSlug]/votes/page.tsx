"use client"
import { use, useState } from "react"
import { brokerCastVote, brokerPost, useVotes } from "@/lib/broker/client"
import type { Vote } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

// The dashboard operator casts ballots under this identity, matching the
// broker's WS UI-action convention where the human is "you". The broker is the
// source of truth for who has voted (vote.ballots), so the disable-after-vote
// state below is read back from server state rather than tracked client-side.
const OPERATOR = "you"

const MIN_OPTIONS = 2
const MAX_OPTIONS = 5

export default function VotesPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const votes = useVotes(workspaceSlug)

  const [question, setQuestion] = useState("")
  const [options, setOptions] = useState<string[]>(["", ""])
  const [threshold, setThreshold] = useState("")
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const list = votes.data?.votes ?? []
  const open = list
    .filter((v) => v.status === "open")
    .sort((a, b) => (b.ts || "").localeCompare(a.ts || ""))
  const closed = list
    .filter((v) => v.status !== "open")
    .sort((a, b) =>
      (b.resolved_at || b.ts || "").localeCompare(a.resolved_at || a.ts || ""),
    )

  const filledOptions = options.map((o) => o.trim()).filter(Boolean)
  const canCreate = question.trim().length > 0 && filledOptions.length >= MIN_OPTIONS

  function setOption(index: number, value: string) {
    setOptions((prev) => prev.map((o, i) => (i === index ? value : o)))
  }

  function addOption() {
    setOptions((prev) => (prev.length >= MAX_OPTIONS ? prev : [...prev, ""]))
  }

  function removeOption(index: number) {
    setOptions((prev) =>
      prev.length <= MIN_OPTIONS ? prev : prev.filter((_, i) => i !== index),
    )
  }

  async function create() {
    if (!canCreate || creating) return
    // Guard against duplicate option labels — the broker tallies by label and a
    // collision would make ballot counts ambiguous.
    const unique = Array.from(new Set(filledOptions))
    if (unique.length < filledOptions.length) {
      setError("Options must be unique.")
      return
    }
    const thr = threshold.trim() ? Number(threshold.trim()) : undefined
    if (thr !== undefined && (!Number.isInteger(thr) || thr < 1)) {
      setError("Threshold must be a whole number of 1 or more.")
      return
    }
    setCreating(true)
    setError(null)
    try {
      await brokerPost(workspaceSlug, "vote", {
        question: question.trim(),
        options: unique,
        threshold: thr,
      })
      setQuestion("")
      setOptions(["", ""])
      setThreshold("")
      votes.refetch()
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
          Votes
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          Multi-option consensus across the mesh. Cast a ballot per vote; the
          broker resolves a winner once ballots cross the threshold or every
          online instance has voted.
        </p>
      </header>

      <div className="mb-8 rounded-sm border border-border bg-surface p-4">
        <div className="mb-3 text-xs uppercase tracking-widest text-text-muted">
          Open a vote
        </div>
        {error && (
          <div className="mb-2 text-xs text-red-400">Create failed: {error}</div>
        )}
        <div className="space-y-3">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Question, e.g. which deploy strategy"
            className="w-full rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <div className="space-y-2">
            {options.map((opt, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  value={opt}
                  onChange={(e) => setOption(i, e.target.value)}
                  placeholder={`Option ${i + 1}`}
                  className="flex-1 rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => removeOption(i)}
                  disabled={options.length <= MIN_OPTIONS}
                  className="rounded-sm border border-border bg-bg px-3 py-2 text-sm text-text-muted disabled:opacity-30 hover:bg-surface-2"
                  aria-label={`Remove option ${i + 1}`}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={addOption}
              disabled={options.length >= MAX_OPTIONS}
              className="rounded-sm border border-border bg-bg px-3 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
            >
              Add option
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              inputMode="numeric"
              placeholder="Threshold (optional)"
              className="w-48 rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
            />
            <button
              onClick={create}
              disabled={!canCreate || creating}
              className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
            >
              {creating ? "Opening" : "Open vote"}
            </button>
            {!canCreate && (
              <span className="text-xs text-text-muted">
                Question and at least {MIN_OPTIONS} options required.
              </span>
            )}
          </div>
        </div>
      </div>

      <section className="mb-8">
        <div className="mb-2 flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">Open</h2>
          <span className="text-xs text-text-muted">{open.length}</span>
        </div>
        {open.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
            No open votes.
          </div>
        ) : (
          <div className="space-y-2">
            {open.map((v) => (
              <OpenVoteCard
                key={v.id}
                v={v}
                slug={workspaceSlug}
                onCast={votes.refetch}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">Resolved</h2>
          <span className="text-xs text-text-muted">{closed.length}</span>
        </div>
        {closed.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
            No resolved votes yet.
          </div>
        ) : (
          <div className="space-y-2">
            {closed.map((v) => (
              <ResolvedVoteCard key={v.id} v={v} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function tally(v: Vote): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const opt of v.options) counts[opt] = 0
  for (const choice of Object.values(v.ballots || {})) {
    if (choice in counts) counts[choice] += 1
  }
  return counts
}

function OpenVoteCard({
  v,
  slug,
  onCast,
}: {
  v: Vote
  slug: string
  onCast: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const counts = tally(v)
  const ballots = Object.entries(v.ballots || {})
  const myChoice = v.ballots?.[OPERATOR]
  const totalBallots = ballots.length

  async function cast(option: string) {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      // brokerCastVote omits the voter; the broker defaults it to "you",
      // which is the dashboard operator identity (OPERATOR) used elsewhere here.
      await brokerCastVote(slug, v.id, option)
      onCast()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-sm border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-text-muted">{v.id}</span>
          <span className="text-sm font-medium">{v.question}</span>
        </div>
        <div className="flex shrink-0 items-baseline gap-3 text-xs text-text-muted">
          {v.threshold != null && <span>threshold: {v.threshold}</span>}
          <span>{totalBallots} cast</span>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {v.options.map((opt) => {
          const count = counts[opt] ?? 0
          const mine = myChoice === opt
          return (
            <div key={opt} className="flex items-center gap-3">
              <button
                onClick={() => cast(opt)}
                disabled={busy || !!myChoice}
                className={
                  "min-w-[120px] rounded-sm border px-3 py-2 text-left text-sm font-medium disabled:cursor-default disabled:opacity-60 " +
                  (mine
                    ? "border-gold bg-[color:var(--gold-tint)] text-gold"
                    : "border-border bg-bg hover:bg-surface-2")
                }
              >
                {opt}
              </button>
              <span className="font-mono text-xs text-text-muted">
                {count} {count === 1 ? "ballot" : "ballots"}
              </span>
            </div>
          )
        })}
      </div>

      {ballots.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-muted">
          {ballots.map(([voter, choice]) => (
            <span key={voter}>
              <span className="font-mono text-text">{voter}</span>: {choice}
            </span>
          ))}
        </div>
      )}

      <div className="mt-2 text-xs text-text-muted">
        {myChoice ? (
          <span>
            You voted <span className="text-text">{myChoice}</span>.
          </span>
        ) : (
          <span>Click an option to cast your ballot.</span>
        )}
      </div>

      {error && (
        <div className="mt-2 text-xs text-red-400">Cast failed: {error}</div>
      )}
    </div>
  )
}

function ResolvedVoteCard({ v }: { v: Vote }) {
  const counts = tally(v)
  const ordered = [...v.options].sort((a, b) => (counts[b] ?? 0) - (counts[a] ?? 0))

  return (
    <div className="rounded-sm border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-text-muted">{v.id}</span>
          <span className="text-sm font-medium">{v.question}</span>
        </div>
        <span className="text-xs font-semibold text-gold">
          winner: {v.winner ?? "—"}
        </span>
      </div>

      <div className="mt-3 space-y-1">
        {ordered.map((opt) => {
          const count = counts[opt] ?? 0
          const won = v.winner === opt
          return (
            <div
              key={opt}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span className={won ? "font-medium text-gold" : "text-text"}>
                {opt}
              </span>
              <span className="font-mono text-xs text-text-muted">
                {count} {count === 1 ? "ballot" : "ballots"}
              </span>
            </div>
          )
        })}
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-text-muted">
        {v.threshold != null && <span>threshold: {v.threshold}</span>}
        <span>resolved: {formatTs(v.resolved_at || v.ts)}</span>
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
