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

export type BrokerState = {
  instances: Instance[]
  messages: Message[]
  tasks: Task[]
  memory: MemoryEntry[]
}
