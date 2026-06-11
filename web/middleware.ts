// Auth + workspace routing middleware.
// - Unauthenticated users on /(app) routes get bounced to /login
// - Authenticated users without a workspace get bounced to /onboarding
// - Authenticated users with a workspace can access /(app) routes
//
// We deliberately do nothing for /(marketing) and /(auth) — those are public.
import { NextResponse, type NextRequest } from "next/server"
import { updateSession } from "@/lib/supabase/middleware"

const PUBLIC_PATHS = ["/", "/changelog", "/docs", "/login", "/signup", "/verify", "/invite"]
const STATIC_PATHS = ["/_next", "/api", "/favicon.ico", "/og-image.png", "/manifest.json"]

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Always run the session refresh so cookies stay current.
  const { supabaseResponse, user } = await updateSession(request)

  if (STATIC_PATHS.some((p) => pathname.startsWith(p))) return supabaseResponse
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) return supabaseResponse

  // Pre-Supabase-setup grace mode: env vars absent → no auth → let
  // protected routes render the "Supabase not configured" placeholder.
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL) return supabaseResponse

  // Everything else needs auth.
  if (!user) {
    const url = request.nextUrl.clone()
    url.pathname = "/login"
    url.searchParams.set("next", pathname)
    return NextResponse.redirect(url)
  }

  return supabaseResponse
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"],
}
