// Server-side Supabase client. Reads/writes the session cookie via next/headers.
// Use in Server Components, Server Actions, and Route Handlers.
import { createServerClient, type CookieOptions } from "@supabase/ssr"
import { cookies } from "next/headers"

// Next 15+: cookies() is async. Callers must `await createClient()`.
export async function createClient() {
  const cookieStore = await cookies()
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get: (name: string) => cookieStore.get(name)?.value,
        set: (name: string, value: string, options: CookieOptions) => {
          try { cookieStore.set({ name, value, ...options }) } catch { /* RSC read-only */ }
        },
        remove: (name: string, options: CookieOptions) => {
          try { cookieStore.set({ name, value: "", ...options }) } catch { /* RSC read-only */ }
        },
      },
    },
  )
}
