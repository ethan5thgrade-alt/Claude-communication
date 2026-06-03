"use client"
import { use, useEffect, useMemo, useRef, useState } from "react"
import { brokerPost, useBrokerPoll } from "@/lib/broker/client"
import type { Channel, Instance, Message } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

// Selection is either the broadcast pseudo-target "all", a single instance id,
// or "channel:<id>" — the same recipient grammar the broker's /api/send uses,
// so the value can be passed straight through as the `to` field.
const CHANNEL_PREFIX = "channel:"

export default function ChatPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const instances = useBrokerPoll<Instance[]>(workspaceSlug, "instances", 5000)
  const channels = useBrokerPoll<{ channels: Channel[] }>(
    workspaceSlug,
    "channels",
    5000,
  )
  const messages = useBrokerPoll<{ messages: Message[] }>(
    workspaceSlug,
    "messages?limit=200",
    2000,
  )

  const [draft, setDraft] = useState("")
  const [to, setTo] = useState<string>("all")
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  const list = messages.data?.messages ?? []
  const peers = instances.data ?? []
  const chans = channels.data?.channels ?? []

  const selectedChannelId = to.startsWith(CHANNEL_PREFIX)
    ? to.slice(CHANNEL_PREFIX.length)
    : null
  const selectedChannel = selectedChannelId
    ? chans.find((c) => c.id === selectedChannelId) ?? null
    : null

  const filtered = useMemo(() => {
    if (selectedChannelId) {
      return list.filter((m) => m.channel === selectedChannelId)
    }
    if (to === "all") {
      // Broadcast view excludes channel-tagged traffic so group chatter does
      // not leak into the mesh-wide feed.
      return list.filter((m) => !m.channel)
    }
    return list.filter(
      (m) =>
        !m.channel &&
        (m.to === to || m.from === to || m.to === "all" || m.to === ""),
    )
  }, [list, to, selectedChannelId])

  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [filtered.length])

  const peerName = (id: string) => peers.find((p) => p.id === id)?.name || id

  async function send() {
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    setSendError(null)
    try {
      await brokerPost(workspaceSlug, "send", {
        from: "web-ui",
        to,
        text,
      })
      setDraft("")
      messages.refetch()
    } catch (e) {
      setSendError(e instanceof Error ? e.message : String(e))
    } finally {
      setSending(false)
    }
  }

  let headerTitle: string
  let headerSub: string
  if (selectedChannel) {
    headerTitle = selectedChannel.name
    headerSub = `${selectedChannel.members.length} member${
      selectedChannel.members.length === 1 ? "" : "s"
    }`
  } else if (to === "all") {
    headerTitle = "All instances"
    headerSub = "Broadcasts and DMs across the mesh."
  } else {
    headerTitle = peerName(to)
    headerSub = "Direct messages."
  }

  let placeholder: string
  if (selectedChannel) {
    placeholder = `Message ${selectedChannel.name}. Enter sends, Shift+Enter for newline.`
  } else if (to === "all") {
    placeholder = "Broadcast to all instances. Enter sends, Shift+Enter for newline."
  } else {
    placeholder = `Message ${peerName(to)}. Enter sends, Shift+Enter for newline.`
  }

  return (
    <div className="flex h-full">
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-surface">
        <div className="overflow-y-auto">
          <div className="border-b border-border px-4 py-3 text-xs uppercase tracking-widest text-text-muted">
            Instances
          </div>
          <PeerRow
            label="All instances"
            sub={`${peers.filter((p) => p.online).length} online`}
            active={to === "all"}
            onClick={() => setTo("all")}
          />
          {peers.map((p) => (
            <PeerRow
              key={p.id}
              label={p.name || p.id}
              sub={p.online ? "online" : "offline"}
              dim={!p.online}
              active={to === p.id}
              onClick={() => setTo(p.id)}
            />
          ))}
          {peers.length === 0 && (
            <div className="px-4 py-3 text-sm text-text-muted">
              No instances connected.
            </div>
          )}

          <div className="flex items-center justify-between border-y border-border px-4 py-3">
            <span className="text-xs uppercase tracking-widest text-text-muted">
              Channels
            </span>
            <button
              onClick={() => setShowCreate(true)}
              className="rounded-sm border border-border bg-bg px-2 py-1 text-xs font-semibold text-text hover:bg-surface-2"
            >
              New channel
            </button>
          </div>
          {chans.map((c) => (
            <PeerRow
              key={c.id}
              label={c.name}
              sub={`${c.members.length} member${c.members.length === 1 ? "" : "s"}`}
              active={selectedChannelId === c.id}
              onClick={() => setTo(CHANNEL_PREFIX + c.id)}
            />
          ))}
          {chans.length === 0 && (
            <div className="px-4 py-3 text-sm text-text-muted">
              No channels yet.
            </div>
          )}
        </div>
      </aside>

      <section className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-3">
          <div>
            <div className="text-sm font-semibold">{headerTitle}</div>
            <div className="text-xs text-text-muted">{headerSub}</div>
            {selectedChannel && selectedChannel.members.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {selectedChannel.members.map((m) => (
                  <span
                    key={m}
                    className="rounded-sm border border-border bg-bg px-1.5 py-0.5 font-mono text-[11px] text-text-muted"
                  >
                    {peerName(m)}
                  </span>
                ))}
              </div>
            )}
          </div>
          {messages.error && (
            <div className="text-xs text-red-400">Lost broker connection. Retrying.</div>
          )}
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4">
          {filtered.length === 0 ? (
            <div className="mt-8 text-center text-sm text-text-muted">
              No messages yet.
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((m) => (
                <MessageRow
                  key={m.id}
                  m={m}
                  channelName={
                    m.channel
                      ? chans.find((c) => c.id === m.channel)?.name ?? m.channel
                      : undefined
                  }
                />
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-border bg-surface px-6 py-4">
          {sendError && (
            <div className="mb-2 text-xs text-red-400">
              Send failed: {sendError}. Check the broker is reachable.
            </div>
          )}
          <div className="flex items-end gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              rows={2}
              placeholder={placeholder}
              className="flex-1 resize-none rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
            />
            <button
              onClick={send}
              disabled={!draft.trim() || sending}
              className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold text-text disabled:opacity-40 hover:bg-surface-2"
            >
              {sending ? "Sending" : "Send"}
            </button>
          </div>
        </div>
      </section>

      {showCreate && (
        <CreateChannelModal
          peers={peers}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => {
            setShowCreate(false)
            channels.refetch()
            setTo(CHANNEL_PREFIX + id)
          }}
          createChannel={(name, members) =>
            brokerPost<{ ok: boolean; channel: Channel }>(workspaceSlug, "channels", {
              name,
              members,
            })
          }
        />
      )}
    </div>
  )
}

function CreateChannelModal({
  peers,
  onClose,
  onCreated,
  createChannel,
}: {
  peers: Instance[]
  onClose: () => void
  onCreated: (channelId: string) => void
  createChannel: (
    name: string,
    members: string[],
  ) => Promise<{ ok: boolean; channel: Channel }>
}) {
  const [name, setName] = useState("")
  const [members, setMembers] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggle(id: string) {
    setMembers((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id],
    )
  }

  async function submit() {
    const trimmed = name.trim()
    if (!trimmed || members.length === 0 || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await createChannel(trimmed, members)
      onCreated(res.channel.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-sm border border-border bg-surface p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-sm font-semibold">Create channel</div>
        <div className="mt-1 text-xs text-text-muted">
          Pick a name and the instances to add as members.
        </div>

        <label className="mt-4 block text-xs uppercase tracking-widest text-text-muted">
          Name
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="#deployments"
          autoFocus
          className="mt-1 w-full rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
        />

        <div className="mt-4 text-xs uppercase tracking-widest text-text-muted">
          Members
        </div>
        <div className="mt-1 max-h-48 overflow-y-auto rounded-sm border border-border">
          {peers.length === 0 ? (
            <div className="px-3 py-3 text-sm text-text-muted">
              No instances connected.
            </div>
          ) : (
            peers.map((p) => (
              <label
                key={p.id}
                className="flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 text-sm last:border-b-0 hover:bg-bg"
              >
                <input
                  type="checkbox"
                  checked={members.includes(p.id)}
                  onChange={() => toggle(p.id)}
                />
                <span className="font-medium">{p.name || p.id}</span>
                <span className="ml-auto text-xs text-text-muted">
                  {p.online ? "online" : "offline"}
                </span>
              </label>
            ))
          )}
        </div>

        {error && (
          <div className="mt-3 text-xs text-red-400">
            Create failed: {error}.
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold text-text hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!name.trim() || members.length === 0 || busy}
            className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold text-text disabled:opacity-40 hover:bg-surface-2"
          >
            {busy ? "Creating" : "Create channel"}
          </button>
        </div>
      </div>
    </div>
  )
}

function PeerRow({
  label,
  sub,
  active,
  dim,
  onClick,
}: {
  label: string
  sub: string
  active: boolean
  dim?: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={
        "flex w-full flex-col gap-0.5 border-b border-border px-4 py-3 text-left transition-colors " +
        (active
          ? "bg-[color:var(--gold-tint)] text-gold"
          : "hover:bg-bg " + (dim ? "text-text-muted" : "text-text"))
      }
    >
      <span className="text-sm font-medium truncate">{label}</span>
      <span className="text-xs text-text-muted">{sub}</span>
    </button>
  )
}

function MessageRow({ m, channelName }: { m: Message; channelName?: string }) {
  const isBroadcast = !m.to || m.to === "all"
  return (
    <div className="rounded-sm border border-border bg-surface px-4 py-3">
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <div className="text-text-muted">
          <span className="font-mono">{m.from || "?"}</span>
          {channelName ? (
            <span className="ml-2">
              <span className="uppercase tracking-widest">channel</span>
              <span className="ml-1 font-mono">{channelName}</span>
            </span>
          ) : isBroadcast ? (
            <span className="ml-2 uppercase tracking-widest">broadcast</span>
          ) : (
            <>
              <span className="mx-1 text-text-muted">to</span>
              <span className="font-mono">{m.to}</span>
            </>
          )}
        </div>
        <time className="text-text-muted">{formatTs(m.ts)}</time>
      </div>
      <div className="mt-1 whitespace-pre-wrap text-sm">{m.text}</div>
    </div>
  )
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  } catch {
    return iso
  }
}
