"use client"
import { use, useEffect, useMemo, useRef, useState } from "react"
import { brokerPost, useBrokerPoll } from "@/lib/broker/client"
import type { Instance, Message } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

export default function ChatPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const instances = useBrokerPoll<Instance[]>(workspaceSlug, "instances", 5000)
  const messages = useBrokerPoll<{ messages: Message[] }>(
    workspaceSlug,
    "messages?limit=200",
    2000,
  )

  const [draft, setDraft] = useState("")
  const [to, setTo] = useState<string>("all")
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  const list = messages.data?.messages ?? []
  const peers = instances.data ?? []

  const filtered = useMemo(() => {
    if (to === "all") return list
    return list.filter(
      (m) => m.to === to || m.from === to || m.to === "all" || m.to === "",
    )
  }, [list, to])

  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [filtered.length])

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

  return (
    <div className="flex h-full">
      <aside className="w-64 shrink-0 border-r border-border bg-surface">
        <div className="border-b border-border px-4 py-3 text-xs uppercase tracking-widest text-text-muted">
          Instances
        </div>
        <div className="overflow-y-auto">
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
        </div>
      </aside>

      <section className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-6 py-3">
          <div>
            <div className="text-sm font-semibold">
              {to === "all" ? "All instances" : peers.find((p) => p.id === to)?.name || to}
            </div>
            <div className="text-xs text-text-muted">
              {to === "all" ? "Broadcasts and DMs across the mesh." : "Direct messages."}
            </div>
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
                <MessageRow key={m.id} m={m} />
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
              placeholder={
                to === "all"
                  ? "Broadcast to all instances. Enter sends, Shift+Enter for newline."
                  : `Message ${peers.find((p) => p.id === to)?.name || to}. Enter sends, Shift+Enter for newline.`
              }
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

function MessageRow({ m }: { m: Message }) {
  const isBroadcast = !m.to || m.to === "all"
  return (
    <div className="rounded-sm border border-border bg-surface px-4 py-3">
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <div className="text-text-muted">
          <span className="font-mono">{m.from || "?"}</span>
          {isBroadcast ? (
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
