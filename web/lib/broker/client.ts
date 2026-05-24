"use client"
import { useEffect, useRef, useState } from "react"

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
