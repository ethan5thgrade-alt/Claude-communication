import { createClient } from "@/lib/supabase/server"

type WorkspaceBroker = { url: string; token: string }

export class BrokerError extends Error {
  constructor(message: string, public status: number) {
    super(message)
    this.name = "BrokerError"
  }
}

export async function resolveBroker(workspaceSlug: string): Promise<WorkspaceBroker> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) throw new BrokerError("Not signed in.", 401)

  const { data: workspace } = await supabase
    .from("workspaces")
    .select("id, broker_url, broker_token")
    .eq("slug", workspaceSlug)
    .single()
  if (!workspace) throw new BrokerError("Workspace not found.", 404)

  const { data: member } = await supabase
    .from("workspace_members")
    .select("role")
    .eq("workspace_id", workspace.id)
    .eq("user_id", user.id)
    .single()
  if (!member) throw new BrokerError("Not a member of this workspace.", 403)

  // Phase 2: workspace fields may be empty; fall back to server env (dev).
  // Phase 3+: every workspace stores its own broker URL/token.
  const url = workspace.broker_url || process.env.BROKER_HTTP || "http://localhost:8765"
  const token = workspace.broker_token || process.env.MESH_TOKEN || ""
  return { url, token }
}

export async function brokerFetch(
  broker: WorkspaceBroker,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = broker.url.replace(/\/$/, "") + path
  const headers = new Headers(init.headers)
  if (broker.token) headers.set("X-Mesh-Token", broker.token)
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  return fetch(url, { ...init, headers, cache: "no-store" })
}

export async function brokerJson<T>(
  broker: WorkspaceBroker,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await brokerFetch(broker, path, init)
  if (!res.ok) {
    throw new BrokerError(`Broker returned ${res.status} on ${path}`, res.status)
  }
  return (await res.json()) as T
}
