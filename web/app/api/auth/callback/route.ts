// Email-verification + OAuth callback handler.
// Exchanges the `?code=` for a session cookie, then redirects to `?next=`.
import { NextResponse, type NextRequest } from "next/server"
import { createClient } from "@/lib/supabase/server"
import { safeNextPath } from "@/lib/safe-next"

export async function GET(request: NextRequest) {
  const url = new URL(request.url)
  const code = url.searchParams.get("code")
  // Guard against open-redirect: `next` is attacker-controlled, so it is matched
  // against an allowlist of real in-app routes and falls back to DEFAULT_NEXT.
  // The result is always an anchored same-origin path, so resolving it against
  // url.origin cannot escape to an external host.
  const next = safeNextPath(url.searchParams.get("next"))

  if (code) {
    const supabase = await createClient()
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) return NextResponse.redirect(new URL(next, url.origin))
  }
  return NextResponse.redirect(new URL("/login?error=callback", url.origin))
}
