import { NextRequest, NextResponse } from "next/server"
import { resolveBroker, brokerUiWsUrl, BrokerError } from "@/lib/broker/server"

// This route holds a long-lived upstream WebSocket open for the duration of
// the SSE stream, so it must run on the Node runtime (Edge has no persistent
// WebSocket client) and must never be cached or statically optimized.
export const runtime = "nodejs"
export const dynamic = "force-dynamic"

type Params = { params: Promise<{ slug: string }> }

// Broker broadcast_ui frames we relay to the browser. The broker emits many
// instance-lifecycle frames (status, typing, log_event, instance_online, ...)
// that the dashboard collections-views do not consume; forwarding only this
// set keeps the stream scoped to the approvals / votes / channels / flows /
// audit / messages surfaces the UI binds to. "init" is the first frame the
// broker sends with the full snapshot.
const FORWARDED_TYPES = new Set([
  "init",
  // approvals collection
  "approvals",
  "approval_request",
  // votes collection
  "votes",
  // channels collection
  "channels",
  // flows collection
  "flows",
  "flow_fired",
  // audit + the state_update deltas that carry audit/collection changes
  "audit",
  "state_update",
  // chat / channel fan-out
  "message",
])

function sseEvent(event: string, data: unknown): string {
  // One SSE event: an `event:` line plus a single `data:` line. The payload is
  // JSON with no embedded newlines (JSON.stringify escapes them), so a single
  // data line is safe.
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

export async function GET(req: NextRequest, { params }: Params): Promise<Response> {
  const { slug } = await params

  // Authenticate the Supabase session and authorize workspace membership
  // (owner/admin) before opening anything upstream. resolveBroker throws
  // BrokerError with the right status for unauthenticated / non-member /
  // viewer / unknown-workspace cases.
  let wsUrl: string
  try {
    const broker = await resolveBroker(slug)
    wsUrl = brokerUiWsUrl(broker)
  } catch (err) {
    if (err instanceof BrokerError) {
      return NextResponse.json({ error: err.message }, { status: err.status })
    }
    const message = err instanceof Error ? err.message : "Unknown error"
    return NextResponse.json({ error: message }, { status: 502 })
  }

  const encoder = new TextEncoder()

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let upstream: WebSocket | null = null
      let closed = false
      let heartbeat: ReturnType<typeof setInterval> | null = null

      const safeEnqueue = (chunk: string): void => {
        if (closed) return
        try {
          controller.enqueue(encoder.encode(chunk))
        } catch {
          // Controller already closed (client went away mid-write). Tear down.
          teardown()
        }
      }

      const teardown = (): void => {
        if (closed) return
        closed = true
        if (heartbeat) clearInterval(heartbeat)
        try {
          upstream?.close()
        } catch {
          /* upstream may already be closing */
        }
        try {
          controller.close()
        } catch {
          /* controller may already be closed */
        }
      }

      // If the client disconnects, abort the upstream and close the stream.
      const onAbort = (): void => teardown()
      if (req.signal.aborted) {
        teardown()
        return
      }
      req.signal.addEventListener("abort", onAbort)

      try {
        upstream = new WebSocket(wsUrl)
      } catch {
        safeEnqueue(sseEvent("error", { error: "Failed to reach broker." }))
        teardown()
        return
      }

      upstream.addEventListener("message", (ev: MessageEvent) => {
        // The broker only ever sends text frames on /ui. Anything else is
        // unexpected and skipped rather than relayed raw.
        if (typeof ev.data !== "string") return
        let payload: { type?: string }
        try {
          payload = JSON.parse(ev.data)
        } catch {
          return
        }
        const type = payload.type
        if (typeof type !== "string" || !FORWARDED_TYPES.has(type)) return
        // The first snapshot becomes the SSE `init` event; everything else is
        // a named broker event the client switches on by `type`.
        safeEnqueue(sseEvent(type === "init" ? "init" : "broker", payload))
      })

      upstream.addEventListener("close", () => {
        // Broker hung up (restart, auth revoked, tunnel drop). Signal the
        // client so it can decide whether to reconnect, then end the stream.
        safeEnqueue(sseEvent("close", { reason: "Broker connection closed." }))
        teardown()
      })

      upstream.addEventListener("error", () => {
        safeEnqueue(sseEvent("error", { error: "Broker connection error." }))
        teardown()
      })

      // Comment-line heartbeat keeps intermediaries from idling out the stream
      // and surfaces a dead client (enqueue throws once the socket is gone).
      heartbeat = setInterval(() => {
        safeEnqueue(`: ping\n\n`)
      }, 25_000)
    },
  })

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      // Disable proxy buffering so events flush immediately.
      "X-Accel-Buffering": "no",
    },
  })
}
