"use client"
import { useState, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import { createClient } from "@/lib/supabase/client"

function LoginInner() {
  const router = useRouter()
  const params = useSearchParams()
  const next = params.get("next") || "/onboarding"
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError(null)
    const supabase = createClient()
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    setLoading(false)
    if (error) { setError(error.message); return }
    router.push(next)
    router.refresh()
  }

  return (
    <div>
      <h1 className="font-display text-2xl font-semibold mb-2">Welcome back</h1>
      <p className="text-sm text-text-muted mb-6">Log in to your workspace.</p>
      <form onSubmit={submit} className="space-y-3">
        <input type="email" required autoFocus placeholder="you@dev.local"
          value={email} onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-sm border border-border bg-surface px-3 py-2.5 text-sm focus:border-gold" />
        <input type="password" required placeholder="Password"
          value={password} onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-sm border border-border bg-surface px-3 py-2.5 text-sm focus:border-gold" />
        {error && <div className="rounded-sm border border-red bg-red/10 px-3 py-2 text-xs text-red">{error}</div>}
        <button type="submit" disabled={loading}
          className="w-full rounded-full bg-gold px-4 py-2.5 text-sm font-semibold text-bg shadow-pop hover:bg-gold-bright disabled:opacity-50">
          {loading ? "Logging in…" : "Log in"}
        </button>
      </form>
      <div className="mt-6 text-center text-xs text-text-muted">
        New here? <Link href="/signup" className="text-gold hover:underline">Create an account</Link>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  )
}
