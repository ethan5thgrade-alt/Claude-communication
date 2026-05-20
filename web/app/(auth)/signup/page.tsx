"use client"
import { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { createClient } from "@/lib/supabase/client"

export default function SignupPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError(null)
    const supabase = createClient()
    const { error } = await supabase.auth.signUp({
      email, password,
      options: {
        emailRedirectTo: `${location.origin}/api/auth/callback?next=/onboarding`,
      },
    })
    setLoading(false)
    if (error) { setError(error.message); return }
    router.push("/verify?email=" + encodeURIComponent(email))
  }

  return (
    <div>
      <h1 className="font-display text-2xl font-semibold mb-2">Create your account</h1>
      <p className="text-sm text-text-muted mb-6">2 instances free forever. No credit card.</p>
      <form onSubmit={submit} className="space-y-3">
        <input
          type="email"
          required
          autoFocus
          placeholder="you@dev.local"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-sm border border-border bg-surface px-3 py-2.5 text-sm focus:border-gold"
        />
        <input
          type="password"
          required
          minLength={8}
          placeholder="Password (8+ characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-sm border border-border bg-surface px-3 py-2.5 text-sm focus:border-gold"
        />
        {error && <div className="rounded-sm border border-red bg-red/10 px-3 py-2 text-xs text-red">{error}</div>}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-sm bg-gold px-4 py-2.5 text-sm font-medium text-bg hover:opacity-95 disabled:opacity-50 transition-opacity"
        >
          {loading ? "Creating…" : "Create account"}
        </button>
      </form>
      <div className="mt-6 text-center text-xs text-text-muted">
        Already have one? <Link href="/login" className="text-gold hover:underline">Log in</Link>
      </div>
    </div>
  )
}
