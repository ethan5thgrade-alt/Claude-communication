import { createClient } from "@/lib/supabase/server"

type WorkspaceBroker = { url: string; token: string }

export class BrokerError extends Error {
  constructor(message: string, public status: number) {
    super(message)
    this.name = "BrokerError"
  }
}

// SSRF guard. In Phase 3 each workspace stores its own broker_url, so the
// value reaching this server-side fetch is user-controlled. Reject anything
// that could pivot the request at internal infrastructure (cloud metadata,
// private ranges, loopback) before we ever call fetch(). Hostname-literal
// based — it does not resolve DNS, so a public name that resolves to a
// private IP (DNS rebinding) is not caught here; that needs a resolve-time
// check at the socket layer and is tracked separately.
function isPrivateHost(host: string): boolean {
  if (host === "0.0.0.0" || host === "::" || host.endsWith(".internal") || host.endsWith(".local")) {
    return true
  }
  // IPv6 unique-local (fc00::/7) and link-local (fe80::/10)
  const h6 = host.replace(/^\[|\]$/g, "")
  if (/^f[cd][0-9a-f]{2}:/i.test(h6) || /^fe[89ab][0-9a-f]:/i.test(h6)) return true
  // IPv4 dotted-quad private / loopback / link-local / CGNAT ranges
  const m = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/)
  if (m) {
    const [a, b] = [Number(m[1]), Number(m[2])]
    if (a === 10 || a === 127) return true
    if (a === 169 && b === 254) return true // link-local incl. 169.254.169.254 metadata
    if (a === 172 && b >= 16 && b <= 31) return true
    if (a === 192 && b === 168) return true
    if (a === 100 && b >= 64 && b <= 127) return true // CGNAT
  }
  return false
}

function assertSafeBrokerUrl(raw: string): void {
  let u: URL
  try {
    u = new URL(raw)
  } catch {
    throw new BrokerError("Broker URL is malformed.", 502)
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") {
    throw new BrokerError("Broker URL must be http(s).", 502)
  }
  const host = u.hostname.toLowerCase()
  const isLocal =
    host === "localhost" || host === "127.0.0.1" || host === "::1" || host.endsWith(".localhost")
  // Dev runs the broker on localhost; production reaches it over a public
  // HTTPS tunnel, so internal targets there are always SSRF, never legitimate.
  if (process.env.NODE_ENV === "production") {
    if (u.protocol !== "https:") throw new BrokerError("Broker URL must use https.", 502)
    if (isLocal || isPrivateHost(host)) {
      throw new BrokerError("Broker URL may not target an internal address.", 502)
    }
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
  assertSafeBrokerUrl(url)
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
