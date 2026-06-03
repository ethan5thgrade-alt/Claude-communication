"use client"
import { use, useMemo, useState } from "react"
import {
  brokerDelete,
  brokerPost,
  useBrokerPoll,
} from "@/lib/broker/client"
import type { AuditEntry, Flow } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

// Audit actions emitted by the flow engine (see broker.py audit() calls).
const FLOW_ACTIONS = new Set([
  "flow_create",
  "flow_delete",
  "flow_toggle",
  "flow_fire",
  "flow_throttled",
  "flow_failed",
  "webhook_attempt",
  "webhook_failed",
])

export default function AutomationsPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const flows = useBrokerPoll<{ flows: Flow[] }>(workspaceSlug, "flows", 3000)
  const audit = useBrokerPoll<{ audit: AuditEntry[] }>(
    workspaceSlug,
    "audit?limit=200",
    3000,
  )

  const [name, setName] = useState("")
  const [trigger, setTrigger] = useState("")
  const [action, setAction] = useState("")
  const [regexError, setRegexError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const list = flows.data?.flows ?? []
  const sorted = useMemo(
    () => [...list].sort((a, b) => (b.ts || "").localeCompare(a.ts || "")),
    [list],
  )

  const flowAudit = useMemo(() => {
    const entries = audit.data?.audit ?? []
    return entries
      .filter((e) => FLOW_ACTIONS.has(e.action))
      .slice(-50)
      .reverse()
  }, [audit.data])

  // Match count per flow id, derived from audit fire entries. Server-authoritative:
  // we count flow_fire rows whose detail references the flow id, never local state.
  const fireCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const e of audit.data?.audit ?? []) {
      if (e.action !== "flow_fire") continue
      const fid = e.detail.split(/\s/)[0]
      if (!fid) continue
      counts[fid] = (counts[fid] ?? 0) + 1
    }
    return counts
  }, [audit.data])

  function validateRegex(value: string): string | null {
    if (!value) return null
    try {
      new RegExp(value)
      return null
    } catch (e) {
      return e instanceof Error ? e.message : "Invalid regular expression"
    }
  }

  async function create() {
    if (!name.trim() || creating) return
    const err = validateRegex(trigger)
    if (err) {
      setRegexError(err)
      return
    }
    setCreating(true)
    setError(null)
    try {
      await brokerPost(workspaceSlug, "flow", {
        name: name.trim(),
        trigger: trigger.trim(),
        action: action.trim(),
      })
      setName("")
      setTrigger("")
      setAction("")
      setRegexError(null)
      flows.refetch()
      audit.refetch()
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
          Automations
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          Flows fire an action when a message matches a trigger regex. Disabled
          flows are skipped by the engine.
        </p>
      </header>

      <div className="mb-8 rounded-sm border border-border bg-surface p-4">
        <div className="mb-3 text-xs uppercase tracking-widest text-text-muted">
          New flow
        </div>
        {error && (
          <div className="mb-2 text-xs text-red-400">Create failed: {error}.</div>
        )}
        <div className="grid gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name, e.g. deploy-notify"
            aria-label="Flow name"
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <div>
            <input
              value={trigger}
              onChange={(e) => {
                setTrigger(e.target.value)
                if (regexError) setRegexError(null)
              }}
              onBlur={() => setRegexError(validateRegex(trigger))}
              placeholder="Trigger regex, e.g. \\bdeploy(ed)?\\b"
              aria-label="Trigger regex"
              className={`w-full rounded-sm border bg-bg px-3 py-2 font-mono text-sm placeholder:text-text-muted focus:outline-none ${
                regexError ? "border-red-400" : "border-border"
              }`}
            />
            {regexError && (
              <div className="mt-1 text-xs text-red-400">
                Invalid regex: {regexError}.
              </div>
            )}
          </div>
          <input
            value={action}
            onChange={(e) => setAction(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            placeholder="Action template, e.g. send #ops Deploy seen: $0"
            aria-label="Action template"
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <div className="flex justify-end">
            <button
              onClick={create}
              disabled={!name.trim() || creating || !!regexError}
              className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
            >
              {creating ? "Creating" : "Create flow"}
            </button>
          </div>
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
          No flows yet.
        </div>
      ) : (
        <div className="space-y-2">
          {sorted.map((f) => (
            <FlowRow
              key={f.id}
              flow={f}
              fireCount={fireCounts[f.id] ?? 0}
              slug={workspaceSlug}
              onChange={() => {
                flows.refetch()
                audit.refetch()
              }}
            />
          ))}
        </div>
      )}

      <section className="mt-10">
        <h2 className="mb-2 text-sm font-semibold">Recent flow activity</h2>
        {flowAudit.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border p-6 text-center text-sm text-text-muted">
            No flow fires recorded yet.
          </div>
        ) : (
          <div className="space-y-1">
            {flowAudit.map((e) => (
              <div
                key={e.id}
                className="flex items-baseline gap-3 rounded-sm border border-border bg-surface px-3 py-2 text-xs"
              >
                <span className="font-mono text-text-muted">{formatTs(e.ts)}</span>
                <span className="font-mono text-gold">{e.action}</span>
                <span className="truncate text-text-muted">{e.detail}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function FlowRow({
  flow,
  fireCount,
  slug,
  onChange,
}: {
  flow: Flow
  fireCount: number
  slug: string
  onChange: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)

  async function run(fn: () => Promise<unknown>) {
    if (busy) return
    setBusy(true)
    setRowError(null)
    try {
      await fn()
      onChange()
    } catch (e) {
      setRowError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  function fire() {
    run(() => brokerPost(slug, `flow/${flow.id}/fire`, {}))
  }

  function toggle() {
    run(() =>
      brokerPost(slug, `flow/${flow.id}/toggle`, { enabled: !flow.enabled }),
    )
  }

  function remove() {
    if (!confirm(`Delete flow ${flow.id} (${flow.name})?`)) return
    run(() => brokerDelete(slug, `flow/${flow.id}`))
  }

  return (
    <div className="rounded-sm border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-text-muted">{flow.id}</span>
          <span className="text-sm font-medium">{flow.name || "(unnamed)"}</span>
          <span
            className={`text-xs ${
              flow.enabled ? "text-gold" : "text-text-muted"
            }`}
          >
            {flow.enabled ? "enabled" : "disabled"}
          </span>
        </div>
        <span className="text-xs text-text-muted">fires: {fireCount}</span>
      </div>

      <div className="mt-2 space-y-1 text-xs">
        <div className="flex gap-2">
          <span className="w-16 shrink-0 text-text-muted">trigger</span>
          <span className="break-all font-mono text-text">
            {flow.trigger || "—"}
          </span>
        </div>
        <div className="flex gap-2">
          <span className="w-16 shrink-0 text-text-muted">action</span>
          <span className="break-all font-mono text-text">
            {flow.action || "—"}
          </span>
        </div>
      </div>

      {rowError && (
        <div className="mt-2 text-xs text-red-400">{rowError}.</div>
      )}

      <div className="mt-3 flex gap-2">
        <button
          onClick={fire}
          disabled={busy}
          className="rounded-sm border border-border bg-bg px-3 py-1.5 text-xs font-semibold disabled:opacity-40 hover:bg-surface-2"
        >
          Fire
        </button>
        <button
          onClick={toggle}
          disabled={busy}
          className="rounded-sm border border-border bg-bg px-3 py-1.5 text-xs font-semibold disabled:opacity-40 hover:bg-surface-2"
        >
          {flow.enabled ? "Disable" : "Enable"}
        </button>
        <button
          onClick={remove}
          disabled={busy}
          className="rounded-sm border border-border bg-bg px-3 py-1.5 text-xs font-semibold text-red-400 disabled:opacity-40 hover:bg-surface-2"
        >
          Delete
        </button>
      </div>
    </div>
  )
}

function formatTs(iso: string): string {
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
