"use client"
import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import { Logo } from "@/components/shared/Logo"

function ConnectInner() {
  const router = useRouter()
  const params = useSearchParams()
  const ws = params.get("ws") || "your-workspace"
  const [copied, setCopied] = useState(false)
  const [detected, setDetected] = useState(false)

  // Poll the broker for connected instances (Phase 1: localhost broker).
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const brokerHttp = process.env.NEXT_PUBLIC_BROKER_HTTP || "http://localhost:8765"
        const r = await fetch(brokerHttp + "/api/instances")
        if (!r.ok) return
        const arr = await r.json()
        if (!cancelled && Array.isArray(arr) && arr.some((i: any) => i.online)) {
          setDetected(true)
        }
      } catch { /* broker may not be up yet — quiet poll */ }
    }
    const id = setInterval(tick, 2000)
    tick()
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const command =
`python3 connect.py \\
  --workspace ${ws} \\
  --name "Claude 1"`

  const copy = async () => {
    await navigator.clipboard.writeText(command)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg">
        <Logo className="h-8 w-8 text-gold mb-6" />
        <div className="text-xs uppercase tracking-widest text-text-muted mb-2">Step 2 of 3</div>
        <h1 className="font-display text-3xl font-semibold mb-2">Connect your first Claude</h1>
        <p className="text-sm text-text-muted mb-6">
          Run this in any Claude Code session. It registers the session as a Mesh instance.
        </p>

        <div className="relative">
          <pre className="rounded-lg border border-border bg-surface p-4 font-mono text-sm text-gold-bright leading-relaxed overflow-x-auto">{command}</pre>
          <button onClick={copy}
            className="absolute top-3 right-3 rounded-sm border border-border bg-surface-2 px-3 py-1 text-xs hover:border-gold">
            {copied ? "Copied ✓" : "Copy"}
          </button>
        </div>

        <div className="mt-6 flex items-center gap-2 text-sm">
          {detected ? (
            <>
              <span className="inline-block h-2 w-2 rounded-full bg-green shadow-pop" />
              <span className="text-green">Instance connected. Looking good.</span>
            </>
          ) : (
            <>
              <span className="inline-block h-2 w-2 rounded-full bg-text-muted animate-pulse" />
              <span className="text-text-muted">Waiting for first connection…</span>
            </>
          )}
        </div>

        <div className="mt-8 flex items-center justify-between">
          <Link href={`/onboarding/invite?ws=${ws}`} className="text-sm text-text-muted hover:text-text">
            Skip for now
          </Link>
          <button
            onClick={() => router.push(`/onboarding/invite?ws=${ws}`)}
            disabled={!detected}
            className="rounded-full bg-gold px-5 py-2.5 text-sm font-semibold text-bg shadow-pop hover:bg-gold-bright disabled:opacity-40"
          >
            Continue →
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ConnectPage() {
  return <Suspense fallback={null}><ConnectInner /></Suspense>
}
