"use client"
import { Suspense, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import { createClient } from "@/lib/supabase/client"
import { Logo } from "@/components/shared/Logo"

function rand(n: number) {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
  let s = ""
  for (let i = 0; i < n; i++) s += chars[Math.floor(Math.random() * chars.length)]
  return s
}

function InviteInner() {
  const router = useRouter()
  const params = useSearchParams()
  const ws = params.get("ws") || ""
  const [email, setEmail] = useState("")
  const [busy, setBusy] = useState(false)
  const [link, setLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const finish = () => router.push(`/${ws}`)

  const generateLink = async () => {
    setBusy(true); setErr(null)
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setErr("Not signed in"); setBusy(false); return }
    // Look up the workspace ID from the slug.
    const { data: workspace } = await supabase
      .from("workspaces").select("id").eq("slug", ws).single()
    if (!workspace) { setErr("Workspace not found"); setBusy(false); return }

    const token = rand(24)
    const { error } = await supabase.from("invites").insert({
      workspace_id: workspace.id, token, created_by: user.id,
      max_uses: 5,
      expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
    })
    setBusy(false)
    if (error) { setErr(error.message); return }
    const base = process.env.NEXT_PUBLIC_APP_URL || location.origin
    setLink(`${base}/invite/${token}`)
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg">
        <Logo className="h-8 w-8 text-gold mb-6" />
        <div className="text-xs uppercase tracking-widest text-text-muted mb-2">Step 3 of 3 (optional)</div>
        <h1 className="font-display text-3xl font-semibold mb-2">Invite a teammate</h1>
        <p className="text-sm text-text-muted mb-6">
          Anyone with this link can join your workspace and connect their own Claudes.
        </p>

        {!link && (
          <button onClick={generateLink} disabled={busy}
            className="rounded-full border border-border bg-surface px-5 py-2.5 text-sm hover:border-gold disabled:opacity-50">
            {busy ? "Generating…" : "Generate invite link"}
          </button>
        )}

        {link && (
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="text-xs text-text-muted mb-2">Share this link (valid for 7 days, up to 5 uses):</div>
            <div className="flex gap-2 items-center">
              <input readOnly value={link}
                className="flex-1 rounded-sm border border-border bg-bg px-3 py-2 font-mono text-xs text-gold-bright" />
              <button onClick={() => navigator.clipboard.writeText(link)}
                className="rounded-sm border border-border px-3 py-2 text-xs hover:border-gold">Copy</button>
            </div>
          </div>
        )}

        {err && <div className="mt-3 rounded-sm border border-red bg-red/10 px-3 py-2 text-xs text-red">{err}</div>}

        <div className="mt-10 flex items-center justify-between">
          <Link href={`/${ws}`} className="text-sm text-text-muted hover:text-text">Do this later</Link>
          <button onClick={finish}
            className="rounded-full bg-gold px-5 py-2.5 text-sm font-semibold text-bg shadow-pop hover:bg-gold-bright">
            Open workspace →
          </button>
        </div>
      </div>
    </div>
  )
}

export default function InvitePage() {
  return <Suspense fallback={null}><InviteInner /></Suspense>
}
