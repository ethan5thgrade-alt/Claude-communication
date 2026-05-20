"use client"
import { useState } from "react"
import { useRouter } from "next/navigation"
import { createClient } from "@/lib/supabase/client"
import { slugify } from "@/lib/utils"
import { Logo } from "@/components/shared/Logo"

export default function OnboardingStep1() {
  const router = useRouter()
  const [name, setName] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const slug = slugify(name) || "your-workspace"

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setErr("Not signed in"); setBusy(false); return }

    const { data, error } = await supabase
      .from("workspaces")
      .insert({ slug, name, owner_id: user.id })
      .select()
      .single()
    if (error) { setErr(error.message); setBusy(false); return }

    const { error: memErr } = await supabase
      .from("workspace_members")
      .insert({ workspace_id: data.id, user_id: user.id, role: "owner" })
    if (memErr) { setErr(memErr.message); setBusy(false); return }

    router.push(`/onboarding/connect?ws=${data.slug}`)
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-md">
        <Logo className="h-8 w-8 text-gold mb-6" />
        <div className="text-xs uppercase tracking-widest text-text-muted mb-2">Step 1 of 3</div>
        <h1 className="font-display text-3xl font-semibold mb-2">Name your workspace</h1>
        <p className="text-sm text-text-muted mb-8">
          A workspace holds your Claudes, channels, and shared memory. You can create more later.
        </p>
        <form onSubmit={submit} className="space-y-4">
          <input
            autoFocus
            type="text"
            required
            maxLength={40}
            placeholder="Acme Skunkworks"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-sm border border-border bg-surface px-3 py-3 text-base focus:border-gold"
          />
          <div className="text-xs text-text-muted">
            URL: <span className="font-mono text-gold">getmesh.dev/{slug}</span>
          </div>
          {err && <div className="rounded-sm border border-red bg-red/10 px-3 py-2 text-xs text-red">{err}</div>}
          <button type="submit" disabled={busy || !name}
            className="w-full rounded-full bg-gold px-4 py-3 text-sm font-semibold text-bg shadow-pop hover:bg-gold-bright disabled:opacity-50">
            {busy ? "Creating…" : "Continue →"}
          </button>
        </form>
      </div>
    </div>
  )
}
