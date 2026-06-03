export type Instance = {
  id: string
  name: string
  project: string
  email: string
  status: string
  task: string
  workload: number
  online: boolean
  role: string
  paused: boolean
  room: string
}

export type Message = {
  id: string
  from: string
  to: string
  text: string
  ts: string
  room?: string
  channel?: string
}

export type Task = {
  id: string
  title: string
  status: string
  priority: string
  assignee?: string
  created_by?: string
  done_by?: string
  result?: string
  ts: string
  deps?: string[]
}

export type MemoryEntry = {
  id: string
  key: string
  value: unknown
  type: string
  by: string
  ts: string
}

export type Approval = {
  id: string
  from: string
  action: string
  risk: "low" | "med" | "high"
  detail: string
  status: "pending" | "approved" | "rejected"
  ts: string
  decided_at?: string
  decision?: boolean
}

export type Vote = {
  id: string
  question: string
  options: string[]
  ballots: Record<string, string>
  threshold: number | null
  status: "open" | "resolved"
  winner: string | null
  created_by: string
  ts: string
  room?: string
  resolved_at?: string
}

export type Flow = {
  id: string
  name: string
  trigger: string
  action: string
  color?: string
  enabled: boolean
  ts: string
}

export type AuditEntry = {
  id: string
  ts: string
  agent: string
  action: string
  detail: string
}

export type Channel = {
  id: string
  name: string
  members: string[]
  created_at: string
}

export type BrokerState = {
  instances: Instance[]
  messages: Message[]
  tasks: Task[]
  memory: MemoryEntry[]
}
