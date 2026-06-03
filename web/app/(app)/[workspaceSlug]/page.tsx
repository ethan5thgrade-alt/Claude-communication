import { createClient } from "@/lib/supabase/server"
import { resolveBroker, brokerJson, BrokerError } from "@/lib/broker/server"
import type { Instance, Message, Task, MemoryEntry } from "@/lib/broker/types"

type Counts = {
  messagesToday: number | null
  tasksActive: number | null
  memoryEntries: number | null
  instancesOnline: number | null
  brokerUnreachable: boolean
}

async function loadCounts(workspaceSlug: string): Promise<Counts> {
  try {
    const broker = await resolveBroker(workspaceSlug)
    // Scope instances to this workspace so a shared broker only surfaces the
    // peers that registered under this slug (server-side filter, not a client
    // reconciliation).
    const ws = encodeURIComponent(workspaceSlug)
    const [msgsRes, tasksRes, memRes, instRes] = await Promise.all([
      brokerJson<{ messages: Message[] }>(broker, "/api/messages?limit=500"),
      brokerJson<{ tasks: Task[] }>(broker, "/api/tasks"),
      brokerJson<{ memory: MemoryEntry[] }>(broker, "/api/memory"),
      brokerJson<Instance[]>(broker, `/api/instances?workspace=${ws}`),
    ])
    const startOfDay = new Date()
    startOfDay.setHours(0, 0, 0, 0)
    const messagesToday = msgsRes.messages.filter(
      (m) => new Date(m.ts).getTime() >= startOfDay.getTime(),
    ).length
    const tasksActive = tasksRes.tasks.filter(
      (t) => t.status !== "Done",
    ).length
    return {
      messagesToday,
      tasksActive,
      memoryEntries: memRes.memory.length,
      instancesOnline: instRes.filter((i) => i.online).length,
      brokerUnreachable: false,
    }
  } catch (e) {
    if (e instanceof BrokerError && e.status < 500) throw e
    return {
      messagesToday: null,
      tasksActive: null,
      memoryEntries: null,
      instancesOnline: null,
      brokerUnreachable: true,
    }
  }
}

export default async function WorkspaceHome({
  params,
}: {
  params: Promise<{ workspaceSlug: string }>
}) {
  const { workspaceSlug } = await params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const { data: profile } = await supabase
    .from("profiles")
    .select("display_name")
    .eq("id", user!.id)
    .single()
  const greeting =
    greet(new Date()) + (profile?.display_name ? `, ${profile.display_name}` : "")

  const counts = await loadCounts(workspaceSlug)
  const fmt = (n: number | null) => (n === null ? "—" : String(n))

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        {greeting}.
      </h1>
      <p className="mt-2 text-text-muted">
        {counts.brokerUnreachable
          ? "Broker is unreachable. Check it is running on the address configured for this workspace."
          : "Live counts from the broker. Open Chat, Tasks, or Memory in the sidebar to act."}
      </p>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Instances online" value={fmt(counts.instancesOnline)} accent />
        <Stat label="Messages today" value={fmt(counts.messagesToday)} />
        <Stat label="Tasks active" value={fmt(counts.tasksActive)} />
        <Stat label="Memory entries" value={fmt(counts.memoryEntries)} />
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: boolean
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-5 shadow-card">
      <div className="text-xs uppercase tracking-widest text-text-muted">{label}</div>
      <div
        className={
          "mt-2 font-display text-2xl font-semibold " + (accent ? "text-gold" : "")
        }
      >
        {value}
      </div>
    </div>
  )
}

function greet(d: Date): string {
  const h = d.getHours()
  if (h < 5) return "Up late"
  if (h < 12) return "Good morning"
  if (h < 17) return "Good afternoon"
  return "Good evening"
}
