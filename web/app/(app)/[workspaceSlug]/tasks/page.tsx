"use client"
import { use, useState } from "react"
import { brokerPost, useBrokerPoll } from "@/lib/broker/client"
import type { Instance, Task } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

const STATUS_ORDER = ["Backlog", "In Progress", "Blocked", "Review", "Done"]

export default function TasksPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const tasks = useBrokerPoll<{ tasks: Task[] }>(workspaceSlug, "tasks", 3000)
  const instances = useBrokerPoll<Instance[]>(workspaceSlug, "instances", 10000)

  const [title, setTitle] = useState("")
  const [assignee, setAssignee] = useState("")
  const [priority, setPriority] = useState("normal")
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const list = tasks.data?.tasks ?? []
  const grouped: Record<string, Task[]> = {}
  for (const s of STATUS_ORDER) grouped[s] = []
  for (const t of list) {
    const bucket = STATUS_ORDER.includes(t.status) ? t.status : "Backlog"
    grouped[bucket].push(t)
  }

  async function create() {
    if (!title.trim() || creating) return
    setCreating(true)
    setError(null)
    try {
      await brokerPost(workspaceSlug, "task", {
        title: title.trim(),
        assignee: assignee || undefined,
        priority,
      })
      setTitle("")
      setAssignee("")
      tasks.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Tasks</h1>
        <p className="mt-1 text-sm text-text-muted">
          Tasks assigned across the mesh. Instances claim, work, and mark done.
        </p>
      </header>

      <div className="mb-8 rounded-sm border border-border bg-surface p-4">
        <div className="mb-3 text-xs uppercase tracking-widest text-text-muted">
          New task
        </div>
        {error && (
          <div className="mb-2 text-xs text-red-400">Create failed: {error}.</div>
        )}
        <div className="flex flex-wrap gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            placeholder="What needs doing"
            className="flex-1 min-w-[200px] rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <select
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm focus:outline-none"
          >
            <option value="">Unassigned</option>
            {(instances.data ?? []).map((i) => (
              <option key={i.id} value={i.id}>
                {i.name || i.id}
              </option>
            ))}
          </select>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="rounded-sm border border-border bg-bg px-3 py-2 text-sm focus:outline-none"
          >
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
          </select>
          <button
            onClick={create}
            disabled={!title.trim() || creating}
            className="rounded-sm border border-border bg-bg px-4 py-2 text-sm font-semibold disabled:opacity-40 hover:bg-surface-2"
          >
            {creating ? "Creating" : "Create"}
          </button>
        </div>
      </div>

      {list.length === 0 ? (
        <div className="rounded-sm border border-dashed border-border p-8 text-center text-sm text-text-muted">
          No tasks yet.
        </div>
      ) : (
        <div className="space-y-6">
          {STATUS_ORDER.map((status) => {
            const items = grouped[status] || []
            if (items.length === 0) return null
            return (
              <section key={status}>
                <div className="mb-2 flex items-baseline gap-2">
                  <h2 className="text-sm font-semibold">{status}</h2>
                  <span className="text-xs text-text-muted">{items.length}</span>
                </div>
                <div className="space-y-2">
                  {items.map((t) => (
                    <TaskRow key={t.id} t={t} />
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}

function TaskRow({ t }: { t: Task }) {
  const priorityClass =
    t.priority === "high"
      ? "text-gold"
      : t.priority === "low"
        ? "text-text-muted"
        : "text-text"
  return (
    <div className="flex items-start gap-4 rounded-sm border border-border bg-surface p-4">
      <div className="flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-text-muted">{t.id}</span>
          <span className="text-sm font-medium">{t.title}</span>
        </div>
        <div className="mt-1 flex items-center gap-3 text-xs text-text-muted">
          <span>
            assignee:{" "}
            <span className="font-mono text-text">{t.assignee || "—"}</span>
          </span>
          <span className={priorityClass}>priority: {t.priority}</span>
          {t.deps && t.deps.length > 0 && (
            <span>deps: {t.deps.join(", ")}</span>
          )}
        </div>
      </div>
    </div>
  )
}
