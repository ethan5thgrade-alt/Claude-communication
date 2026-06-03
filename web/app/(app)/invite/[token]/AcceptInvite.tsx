"use client"
import { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { createClient } from "@/lib/supabase/client"

// Accept action for an invite. Calls the redeem_invite RPC (server-authoritative
// validation + membership insert), then navigates to the workspace home.
export function AcceptInvite({
  token,
  workspaceSlug,
}: {
  token: string
  workspaceSlug: string
}) {
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const accept = async () => {
    setBusy(true)
    setErr(null)
    const supabase = createClient()
    const { data, error } = await supabase.rpc("redeem_invite", { invite_token: token })
    if (error) {
      setBusy(false)
      setErr(error.message)
      return
    }
    // RPC returns the workspace slug; fall back to the previewed slug.
    const slug = (typeof data === "string" && data) || workspaceSlug
    router.push(`/${slug}`)
    router.refresh()
  }

  return (
    <div>
      <div className="flex items-center gap-3">
        <button
          onClick={accept}
          disabled={busy}
          className="rounded-full bg-gold px-5 py-2.5 text-sm font-semibold text-bg shadow-pop hover:bg-gold-bright disabled:opacity-50"
        >
          {busy ? "Joining…" : "Accept invite"}
        </button>
        <Link href="/" className="text-sm text-text-muted hover:text-text">
          Decline
        </Link>
      </div>
      {err && (
        <div className="mt-3 rounded-sm border border-red bg-red/10 px-3 py-2 text-xs text-red">
          {err}
        </div>
      )}
    </div>
  )
}
