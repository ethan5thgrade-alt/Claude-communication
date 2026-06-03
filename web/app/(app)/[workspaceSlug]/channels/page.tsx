"use client"
import { use, useState } from "react"
import {
  brokerCreateChannel,
  brokerDeleteChannel,
  useBrokerPoll,
  useChannels,
} from "@/lib/broker/client"
import type { Channel, Instance } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

type InstanceMeta = { name: string; online: boolean }

export default function ChannelsPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  // Server is authoritative for the channel list and its members; the page only
  // polls and never reconciles membership client-side.
  const channels = useChannels(workspaceSlug, 3000)
  const instances = useBrokerPoll<Instance[]>(
    workspaceSlug,
    `instances?workspace=${encodeURIComponent(workspaceSlug)}`,
    10000,
  )

  const [name, setName] = useState("")
  const [members, setMembers] = useState<string[]>([])
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // id -> { name, online }, built from /api/instances so member chips can show a
  // display name and live presence dot instead of a raw instance id.
  const instanceMap: Record<string, InstanceMeta> = {}
  for (const i of instances.data ?? []) {
    instanceMap[i.id] = { name: i.name || i.id, online: !!i.online }
  }

  const list = [...(channels.data?.channels ?? [])].sort((a, b) =>
    (b.created_at || "").localeCompare(a.created_at || ""),
  )
  const instanceList = instances.data ?? []
  const canCreate = name.trim().length > 0 && members.length >= 1

  function toggleMember(id: string) {
    setMembers((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id],
    )
  }

  async function create() {
    if (!canCreate || creating) return
    setCreating(true)
    setError(null)
    try {
      await brokerCreateChannel(workspaceSlug, name.trim(), members)
      setName("")
      setMembers([])
      channels.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  async function remove(c: Channel) {
    if (!confirm(`Delete channel "${c.name}"? This cannot be undone.`)) return
    setError(null)
    try {
      await brokerDeleteChannel(workspaceSlug, c.id)
      channels.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  // Distinguish "still loading" from "loaded and empty" so the empty state does
  // not flash before the first poll resolves.
  const loaded = channels.data != null

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8">
        <h1 className="font-display text-2xl font-semibold tracking-tight">
          Channels
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          Server-side groups for message routing. Send to a channel to fan a
          message out to every member instance.
        </p>
      </header>

      <div className="mb-8 rounded-sm border border-border bg-surface p-4">
        <div className="mb-3 text-xs uppercase tracking-widest text-text-muted">
          New channel
        </div>
        {error && (
          <div className="mb-2 text-xs text-red-400">Request failed: {error}.</div>
        )}
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Channel name, e.g. deploy-crew"
            aria-label="Channel name"
            className="w-full rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <div>
            <div className="mb-2 text-xs text-text-muted">
              Members ({members.length} selected)
            </div>
            {instanceList.length === 0 ? (
              <div className="rounded-sm border border-dashed border-border p-4 text-center text-xs text-text-muted">
                No instances connected. Start an instance to add members.
              </div>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {instanceList.map((i) => {
                  const checked = members.includes(i.id)
                  return (
                    <label
                      key={i.id}
                      className={
                        "flex cursor-pointer items-center gap-2 rounded-sm border px-3 py-2 text-sm " +
                        (checked
                          ? "border-gold bg-[color:var(--gold-tint)] text-gold"
                          : "border-border bg-bg hover:bg-surface-2")
                      }
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleMember(i.id)}
                        className="accent-[color:var(--gold)]"
                      />
                      <span
                        aria-hidden
                        className={`inline-block h-2 w-2 rounded-full ${
                          i.online ? "bg-green-400" : "bg-text-muted"
                        }`}
                      />
                      <span className="font-mono">{i.name || i.id}</span>
                    </label>
                  )
                })}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={create}
              disabled={!canCreate || creating}
              className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
            >
              {creating ? "Creating" : "Create channel"}
            </button>
            {!canCreate && (
              <span className="text-xs text-text-muted">
                Name and at least 1 member required.
              </span>
            )}
          </div>
        </div>
      </div>

      <section>
        <div className="mb-2 flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">Channels</h2>
          <span className="text-xs text-text-muted">{list.length}</span>
        </div>
        {!loaded ? (
          <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
            Loading channels.
          </div>
        ) : list.length === 0 ? (
          <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
            No channels yet.
          </div>
        ) : (
          <div className="space-y-2">
            {list.map((c) => (
              <ChannelRow
                key={c.id}
                c={c}
                instanceMap={instanceMap}
                onDelete={() => remove(c)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function ChannelRow({
  c,
  instanceMap,
  onDelete,
}: {
  c: Channel
  instanceMap: Record<string, InstanceMeta>
  onDelete: () => void
}) {
  const count = c.members.length
  return (
    <div className="flex items-start gap-4 rounded-sm border border-border bg-surface p-4">
      <div className="flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-text-muted">{c.id}</span>
          <span className="text-sm font-medium">{c.name}</span>
          <span className="text-xs text-text-muted">
            {count} {count === 1 ? "member" : "members"}
          </span>
        </div>
        {count > 0 && (
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-muted">
            {c.members.map((id) => {
              const meta = instanceMap[id]
              const online = meta?.online ?? false
              return (
                <span key={id} className="inline-flex items-center gap-1">
                  <span
                    aria-hidden
                    className={`inline-block h-2 w-2 rounded-full ${
                      online ? "bg-green-400" : "bg-text-muted"
                    }`}
                  />
                  <span className="font-mono text-text">{meta?.name ?? id}</span>
                </span>
              )
            })}
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          onClick={onDelete}
          className="rounded-sm border border-border bg-bg px-3 py-1 text-xs font-semibold text-red-400 hover:bg-surface-2"
        >
          Delete
        </button>
      </div>
    </div>
  )
}
