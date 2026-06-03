import { NextRequest, NextResponse } from "next/server"
import { resolveBroker, brokerFetch, BrokerError } from "@/lib/broker/server"

type Params = { params: Promise<{ slug: string; path: string[] }> }

async function proxy(req: NextRequest, { params }: Params): Promise<NextResponse> {
  const { slug, path } = await params
  try {
    // Reject anything that could escape the /api/ namespace ("..", encoded
    // slashes, dots) before it is joined into the upstream path. Broker REST
    // segments are all plain [a-z0-9_-] tokens (endpoint names + ids).
    if (!path.every((seg) => /^[A-Za-z0-9_-]+$/.test(seg))) {
      return NextResponse.json({ error: "Invalid broker path." }, { status: 400 })
    }
    const broker = await resolveBroker(slug)
    const search = req.nextUrl.search ?? ""
    const upstreamPath = "/api/" + path.join("/") + search
    const body =
      req.method === "GET" || req.method === "HEAD" ? undefined : await req.text()
    const upstream = await brokerFetch(broker, upstreamPath, {
      method: req.method,
      body,
      headers: { "Content-Type": req.headers.get("content-type") || "application/json" },
    })
    const text = await upstream.text()
    return new NextResponse(text, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") || "application/json" },
    })
  } catch (err) {
    if (err instanceof BrokerError) {
      return NextResponse.json({ error: err.message }, { status: err.status })
    }
    const message = err instanceof Error ? err.message : "Unknown error"
    return NextResponse.json({ error: message }, { status: 502 })
  }
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const DELETE = proxy
