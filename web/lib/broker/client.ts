"use client"
import { useEffect, useRef, useState } from "react"
import type { Approval, Channel, Vote } from "@/lib/broker/types"

export class BrokerClientError extends Error {
  constructor(message: string, public status: number) {
    super(message)
  }
}

async function call<T>(
  slug: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`/api/workspaces/${slug}/broker/${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const j = await res.json()
      if (j?.error) detail = j.error
    } catch {}
    throw new BrokerClientError(detail, res.status)
  }
  return (await res.json()) as T
}

export function brokerGet<T>(slug: string, path: string) {
  return call<T>(slug, path)
}

export function brokerPost<T>(slug: string, path: string, body: unknown) {
  return call<T>(slug, path, { method: "POST", body: JSON.stringify(body) })
}

export function brokerPut<T>(slug: string, path: string, body: unknown) {
  return call<T>(slug, path, { method: "PUT", body: JSON.stringify(body) })
}

export function brokerDelete<T>(slug: string, path: string) {
  return call<T>(slug, path, { method: "DELETE" })
}

export function useBrokerPoll<T>(
  slug: string,
  path: string,
  intervalMs = 2000,
): { data: T | null; error: string | null; refetch: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)

  async function tick() {
    try {
      const next = await brokerGet<T>(slug, path)
      if (!cancelled.current) {
        setData(next)
        setError(null)
      }
    } catch (e) {
      if (!cancelled.current) {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
  }

  useEffect(() => {
    cancelled.current = false
    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      cancelled.current = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, path, intervalMs])

  return { data, error, refetch: tick }
}

// ---- approvals ----

export function useApprovals(slug: string, intervalMs = 3000) {
  return useBrokerPoll<{ approvals: Approval[] }>(slug, "approvals", intervalMs)
}

export function brokerApprove(slug: string, id: string, approved: boolean) {
  return brokerPost<{ ok: boolean; approval: Approval }>(
    slug,
    `approval/${id}/respond`,
    { approved },
  )
}

// ---- votes ----

export function useVotes(slug: string, intervalMs = 3000) {
  return useBrokerPoll<{ votes: Vote[] }>(slug, "votes", intervalMs)
}

export function brokerCastVote(slug: string, voteId: string, option: string) {
  return brokerPost<{ ok: boolean; vote: Vote }>(
    slug,
    `vote/${voteId}/cast`,
    { option },
  )
}

// ---- channels ----
// Server-side group routing. The broker owns the channel list (id, name,
// members); the page polls GET /api/channels and never tracks membership
// client-side.

export function useChannels(slug: string, intervalMs = 3000) {
  return useBrokerPoll<{ channels: Channel[] }>(slug, "channels", intervalMs)
}

export function brokerCreateChannel(
  slug: string,
  name: string,
  members: string[],
) {
  return brokerPost<{ ok: boolean; channel: Channel }>(slug, "channels", {
    name,
    members,
  })
}

export function brokerDeleteChannel(slug: string, channelId: string) {
  return brokerDelete<{ ok: boolean; removed: number }>(
    slug,
    `channels/${channelId}`,
  )
}
