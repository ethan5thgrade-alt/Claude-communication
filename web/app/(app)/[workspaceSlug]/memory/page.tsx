"use client"
import { use, useState } from "react"
import { brokerPost, useBrokerPoll } from "@/lib/broker/client"
import type { MemoryEntry } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

const TYPES = ["contract", "decision", "constraint", "note"]

export default function MemoryPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const entries = useBrokerPoll<{ memory: MemoryEntry[] }>(
    workspaceSlug,
    "memory",
    3000,
  )

  const [key, setKey] = useState("")
  const [value, setValue] = useState("")
  const [memType, setMemType] = useState("contract")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const list = entries.data?.memory ?? []
  const sorted = [...list].sort((a, b) => (b.ts || "").localeCompare(a.ts || ""))

  async function save() {
    if (!key.trim() || saving) return
    setSaving(true)
    setError(null)
    try {
      await brokerPost(workspaceSlug, "memory", {
        key: key.trim(),
        value,
        mem_type: memType,
      })
      setKey("")
      setValue("")
      entries.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Memory</h1>
        <p className="mt-1 text-sm text-text-muted">
          Shared facts and decisions every instance can read. Append-only.
        </p>
      </header>

      <div className="mb-8 rounded-sm border border-border bg-surface p-4">
        <div className="mb-3 text-xs uppercase tracking-widest text-text-muted">
          Write entry
        </div>
        {error && (
          <div className="mb-2 text-xs text-red-400">Save failed: {error}.</div>
        )}
        <div className="grid gap-2 sm:grid-cols-[2fr_3fr_auto_auto]">
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Key, e.g. api.endpoint"
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            placeholder="Value"
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <select
            value={memType}
            onChange={(e) => setMemType(e.target.value)}
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm focus:outline-none"
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button
            onClick={save}
            disabled={!key.trim() || saving}
            className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
          >
            {saving ? "Saving" : "Save"}
          </button>
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
          No memory entries yet.
        </div>
      ) : (
        <div className="space-y-2">
          {sorted.map((e) => (
            <MemoryRow key={e.id} e={e} />
          ))}
        </div>
      )}
    </div>
  )
}

function MemoryRow({ e }: { e: MemoryEntry }) {
  return (
    <div className="rounded-sm border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3 text-xs text-text-muted">
        <span className="font-mono text-text">{e.key}</span>
        <span>{formatTs(e.ts)}</span>
      </div>
      <div className="mt-1 whitespace-pre-wrap break-words text-sm">
        {typeof e.value === "string" ? e.value : JSON.stringify(e.value)}
      </div>
      <div className="mt-2 flex items-center gap-3 text-xs text-text-muted">
        <span>type: {e.type}</span>
        <span>
          by: <span className="font-mono">{e.by}</span>
        </span>
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
