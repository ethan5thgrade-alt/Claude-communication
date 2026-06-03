// Token-based invite redemption.
//
// Flow:
//   1. Parse the token from the route params.
//   2. Look up the invite via the preview_invite RPC (SECURITY DEFINER — a
//      non-member cannot read invites/workspaces directly under 0001 RLS).
//   3. Unknown token -> 404.
//   4. Unauthenticated -> redirect to /signup with next pointing back here so
//      the user lands on this page again after verifying their account.
//   5. Authenticated -> show workspace name + member count and an Accept
//      action. Acceptance runs server-side via the redeem_invite RPC, which
//      validates expiry/use-limit, inserts workspace_members, and bumps the
//      use count. On success the client navigates to the workspace home.
//
// Expired / exhausted invites render a terminal state; acceptance is blocked
// both in the UI and inside redeem_invite.
import { redirect, notFound } from "next/navigation"
import { createClient } from "@/lib/supabase/server"
import { Logo } from "@/components/shared/Logo"
import { AcceptInvite } from "./AcceptInvite"

type Preview = {
  workspace_id: string
  workspace_slug: string
  workspace_name: string
  member_count: number
  expired: boolean
  exhausted: boolean
}

export default async function InviteRedemptionPage({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = await params

  // Pre-Supabase grace mode: no env -> render a clear placeholder instead of
  // crashing the client constructor.
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL) {
    return (
      <Shell>
        <h1 className="font-display text-3xl font-semibold mb-2">Invite</h1>
        <p className="text-sm text-text-muted">Supabase is not configured for this deployment.</p>
      </Shell>
    )
  }

  const supabase = await createClient()
  // preview_invite is a set-returning SQL function; without generated DB types
  // the client returns `unknown`, so narrow it here.
  const { data } = await supabase.rpc("preview_invite", { invite_token: token })
  const rows = (data as Preview[] | null) ?? []
  const preview = rows[0]
  if (!preview) notFound()

  const { data: { user } } = await supabase.auth.getUser()
  if (!user) {
    redirect(`/signup?next=${encodeURIComponent(`/invite/${token}`)}`)
  }

  if (preview.expired || preview.exhausted) {
    return (
      <Shell>
        <h1 className="font-display text-3xl font-semibold mb-2">{preview.workspace_name}</h1>
        <p className="text-sm text-text-muted mb-6">
          {preview.expired
            ? "This invite has expired. Ask a workspace member for a new link."
            : "This invite has reached its use limit. Ask a workspace member for a new link."}
        </p>
      </Shell>
    )
  }

  const members = preview.member_count
  return (
    <Shell>
      <div className="text-xs uppercase tracking-widest text-text-muted mb-2">Workspace invite</div>
      <h1 className="font-display text-3xl font-semibold mb-2">{preview.workspace_name}</h1>
      <p className="text-sm text-text-muted mb-6">
        You have been invited to join <span className="text-text">{preview.workspace_name}</span>
        {" — "}
        {members} {members === 1 ? "member" : "members"}. Accepting adds you as a member and
        gives you access to its instances, channels, and shared memory.
      </p>
      <AcceptInvite token={token} workspaceSlug={preview.workspace_slug} />
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg">
        <Logo className="h-8 w-8 text-gold mb-6" />
        {children}
      </div>
    </div>
  )
}
