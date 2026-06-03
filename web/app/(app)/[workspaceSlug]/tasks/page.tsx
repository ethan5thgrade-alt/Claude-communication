"use client"
import { use, useState } from "react"
import {
  brokerPost,
  brokerPut,
  brokerDelete,
  useBrokerPoll,
} from "@/lib/broker/client"
import { useModalDismiss } from "@/lib/use-modal-dismiss"
import type { Instance, Task } from "@/lib/broker/types"

type Props = { params: Promise<{ workspaceSlug: string }> }

const STATUS_ORDER = ["Backlog", "In Progress", "Blocked", "Review", "Done"]
const PRIORITY_ORDER = ["low", "normal", "high"]

type InstanceMeta = { name: string; online: boolean }

export default function TasksPage({ params }: Props) {
  const { workspaceSlug } = use(params)

  const tasks = useBrokerPoll<{ tasks: Task[] }>(workspaceSlug, "tasks", 3000)
  const instances = useBrokerPoll<Instance[]>(
    workspaceSlug,
    `instances?workspace=${encodeURIComponent(workspaceSlug)}`,
    10000,
  )

  const [title, setTitle] = useState("")
  const [assignee, setAssignee] = useState("")
  const [priority, setPriority] = useState("normal")
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)

  // id -> { name, online }. Built from /api/instances so a row can show the
  // assignee's display name and a live online indicator.
  const instanceMap: Record<string, InstanceMeta> = {}
  for (const i of instances.data ?? []) {
    instanceMap[i.id] = { name: i.name || i.id, online: !!i.online }
  }

  const list = tasks.data?.tasks ?? []
  const grouped: Record<string, Task[]> = {}
  for (const s of STATUS_ORDER) grouped[s] = []
  for (const t of list) {
    const bucket = STATUS_ORDER.includes(t.status) ? t.status : "Backlog"
    grouped[bucket].push(t)
  }

  // The modal reads from the live polled list so a refetch reflects server
  // edits immediately. If the task disappears (deleted elsewhere) the modal
  // closes itself.
  const detail = detailId ? (list.find((t) => t.id === detailId) ?? null) : null

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

  async function setStatus(t: Task, status: string) {
    if (status === t.status) return
    setError(null)
    try {
      await brokerPut(workspaceSlug, `task/${t.id}`, { status })
      tasks.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function remove(t: Task) {
    setError(null)
    try {
      await brokerDelete(workspaceSlug, `task/${t.id}`)
      if (detailId === t.id) setDetailId(null)
      tasks.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
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
          <div className="mb-2 text-xs text-red-400">Request failed: {error}.</div>
        )}
        <div className="flex flex-wrap gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            placeholder="What needs doing"
            aria-label="Task title"
            className="flex-1 min-w-[200px] rounded-sm border border-border bg-bg px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none"
          />
          <select
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
            aria-label="Task assignee"
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
            aria-label="Task priority"
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
                    <TaskRow
                      key={t.id}
                      t={t}
                      instanceMap={instanceMap}
                      onStatus={(s) => setStatus(t, s)}
                      onDetails={() => setDetailId(t.id)}
                      onDelete={() => remove(t)}
                    />
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      )}

      {detail && (
        <TaskDetailModal
          t={detail}
          workspaceSlug={workspaceSlug}
          instances={instances.data ?? []}
          instanceMap={instanceMap}
          onSaved={() => tasks.refetch()}
          onClose={() => setDetailId(null)}
        />
      )}
    </div>
  )
}

function AssigneeBadge({
  id,
  instanceMap,
}: {
  id?: string
  instanceMap: Record<string, InstanceMeta>
}) {
  if (!id) return <span className="font-mono text-text">—</span>
  const meta = instanceMap[id]
  const name = meta?.name ?? id
  const online = meta?.online ?? false
  return (
    <span className="inline-flex items-center gap-1">
      <span
        aria-hidden
        className={`inline-block h-2 w-2 rounded-full ${
          online ? "bg-green-400" : "bg-text-muted"
        }`}
      />
      <span className="font-mono text-text">{name}</span>
      <span className="text-text-muted">({online ? "online" : "offline"})</span>
    </span>
  )
}

function TaskRow({
  t,
  instanceMap,
  onStatus,
  onDetails,
  onDelete,
}: {
  t: Task
  instanceMap: Record<string, InstanceMeta>
  onStatus: (status: string) => void
  onDetails: () => void
  onDelete: () => void
}) {
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
            assignee: <AssigneeBadge id={t.assignee} instanceMap={instanceMap} />
          </span>
          <span className={priorityClass}>priority: {t.priority}</span>
          {t.deps && t.deps.length > 0 && <span>deps: {t.deps.join(", ")}</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <select
          value={STATUS_ORDER.includes(t.status) ? t.status : "Backlog"}
          onChange={(e) => onStatus(e.target.value)}
          aria-label="Task status"
          className="rounded-sm border border-border bg-bg px-2 py-1 text-xs focus:outline-none"
        >
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button
          onClick={onDetails}
          className="rounded-sm border border-border bg-bg px-3 py-1 text-xs font-semibold hover:bg-surface-2"
        >
          Details
        </button>
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

function TaskDetailModal({
  t,
  workspaceSlug,
  instances,
  instanceMap,
  onSaved,
  onClose,
}: {
  t: Task
  workspaceSlug: string
  instances: Instance[]
  instanceMap: Record<string, InstanceMeta>
  onSaved: () => void
  onClose: () => void
}) {
  // Online instances are the assignment candidates, matching the create form.
  const onlineInstances = instances.filter((i) => i.online)
  // Escape-to-close + focus management (document-level, so it works regardless
  // of where focus sits when the modal opens).
  const dialogRef = useModalDismiss<HTMLDivElement>(onClose)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className="w-full max-w-lg rounded-sm border border-border bg-surface p-6 focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="font-mono text-xs text-text-muted">{t.id}</div>
            <h2 id="modal-title" className="truncate text-lg font-semibold">
              {t.title}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-sm border border-border bg-bg px-3 py-1 text-xs font-semibold hover:bg-surface-2"
          >
            Close
          </button>
        </div>
        <dl className="space-y-3 text-sm">
          <TitleEditor
            t={t}
            workspaceSlug={workspaceSlug}
            onSaved={onSaved}
          />
          <PriorityEditor
            t={t}
            workspaceSlug={workspaceSlug}
            onSaved={onSaved}
          />
          <AssigneeEditor
            t={t}
            workspaceSlug={workspaceSlug}
            instances={onlineInstances}
            instanceMap={instanceMap}
            onSaved={onSaved}
          />
          <DetailField label="Status" value={t.status} />
          <DetailField label="Created by" value={t.created_by || "—"} />
          <DetailField label="Done by" value={t.done_by || "—"} />
          <DetailField
            label="Dependencies"
            value={t.deps && t.deps.length > 0 ? t.deps.join(", ") : "—"}
          />
          <DetailField label="Created" value={t.ts || "—"} />
          <div className="flex gap-3">
            <dt className="w-28 shrink-0 text-text-muted">Result</dt>
            <dd className="whitespace-pre-wrap break-words text-text">
              {t.result || "—"}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  )
}

// Wraps a single editable field: PUT the patch, wait for the parent refetch,
// surface a per-field error on failure. No optimistic state — the field reads
// from the server-backed task `t` on the next poll/refetch.
function useFieldSave(
  workspaceSlug: string,
  taskId: string,
  onSaved: () => void,
) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(patch: Record<string, unknown>): Promise<boolean> {
    setSaving(true)
    setError(null)
    try {
      await brokerPut(workspaceSlug, `task/${taskId}`, patch)
      onSaved()
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setSaving(false)
    }
  }

  return { save, saving, error }
}

function FieldError({ error }: { error: string | null }) {
  if (!error) return null
  return <div className="mt-1 text-xs text-red-400">Update failed: {error}.</div>
}

function TitleEditor({
  t,
  workspaceSlug,
  onSaved,
}: {
  t: Task
  workspaceSlug: string
  onSaved: () => void
}) {
  const { save, saving, error } = useFieldSave(workspaceSlug, t.id, onSaved)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(t.title)

  function begin() {
    setDraft(t.title)
    setEditing(true)
  }

  async function commit() {
    const next = draft.trim()
    if (!next || next === t.title) {
      setEditing(false)
      return
    }
    const ok = await save({ title: next })
    if (ok) setEditing(false)
  }

  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 pt-1 text-text-muted">Title</dt>
      <dd className="min-w-0 flex-1">
        {editing ? (
          <div className="flex flex-wrap items-center gap-2">
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit()
                if (e.key === "Escape") setEditing(false)
              }}
              aria-label="Task title"
              className="min-w-[180px] flex-1 rounded-sm border border-border bg-bg px-2 py-1 text-sm focus:outline-none"
            />
            <button
              onClick={commit}
              disabled={saving}
              className="rounded-sm border border-border bg-bg px-3 py-1 text-xs font-semibold disabled:opacity-40 hover:bg-surface-2"
            >
              {saving ? "Saving" : "Save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              disabled={saving}
              className="rounded-sm border border-border bg-bg px-3 py-1 text-xs font-semibold disabled:opacity-40 hover:bg-surface-2"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="break-words text-text">{t.title}</span>
            <button
              onClick={begin}
              className="rounded-sm border border-border bg-bg px-2 py-0.5 text-xs font-semibold hover:bg-surface-2"
            >
              Edit
            </button>
          </div>
        )}
        <FieldError error={error} />
      </dd>
    </div>
  )
}

function PriorityEditor({
  t,
  workspaceSlug,
  onSaved,
}: {
  t: Task
  workspaceSlug: string
  onSaved: () => void
}) {
  const { save, saving, error } = useFieldSave(workspaceSlug, t.id, onSaved)

  async function change(next: string) {
    if (next === t.priority) return
    await save({ priority: next })
  }

  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 pt-1 text-text-muted">Priority</dt>
      <dd className="min-w-0 flex-1">
        <select
          value={PRIORITY_ORDER.includes(t.priority) ? t.priority : "normal"}
          onChange={(e) => change(e.target.value)}
          disabled={saving}
          aria-label="Task priority"
          className="rounded-sm border border-border bg-bg px-2 py-1 text-sm disabled:opacity-40 focus:outline-none"
        >
          {PRIORITY_ORDER.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <FieldError error={error} />
      </dd>
    </div>
  )
}

function AssigneeEditor({
  t,
  workspaceSlug,
  instances,
  instanceMap,
  onSaved,
}: {
  t: Task
  workspaceSlug: string
  instances: Instance[]
  instanceMap: Record<string, InstanceMeta>
  onSaved: () => void
}) {
  const { save, saving, error } = useFieldSave(workspaceSlug, t.id, onSaved)

  async function change(next: string) {
    if (next === (t.assignee || "")) return
    await save({ assignee: next })
  }

  // The current assignee may be offline (so absent from the online list). Keep
  // it selectable so a save does not silently drop it.
  const current = t.assignee || ""
  const showCurrent =
    current !== "" && !instances.some((i) => i.id === current)

  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 pt-1 text-text-muted">Assignee</dt>
      <dd className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={current}
            onChange={(e) => change(e.target.value)}
            disabled={saving}
            aria-label="Task assignee"
            className="rounded-sm border border-border bg-bg px-2 py-1 text-sm disabled:opacity-40 focus:outline-none"
          >
            <option value="">Unassigned</option>
            {showCurrent && (
              <option value={current}>
                {instanceMap[current]?.name ?? current} (offline)
              </option>
            )}
            {instances.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name || i.id}
              </option>
            ))}
          </select>
          <AssigneeBadge id={t.assignee} instanceMap={instanceMap} />
        </div>
        <FieldError error={error} />
      </dd>
    </div>
  )
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 text-text-muted">{label}</dt>
      <dd className="break-words text-text">{value}</dd>
    </div>
  )
}
