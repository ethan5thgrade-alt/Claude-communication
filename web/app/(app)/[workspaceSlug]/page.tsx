import { createClient } from "@/lib/supabase/server"

export default async function WorkspaceHome({ params }: { params: { workspaceSlug: string } }) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const { data: profile } = await supabase
    .from("profiles").select("display_name").eq("id", user!.id).single()
  const greeting = greet(new Date()) + (profile?.display_name ? `, ${profile.display_name}` : "")

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <h1 className="font-display text-3xl font-semibold tracking-tight">{greeting}.</h1>
      <p className="mt-2 text-text-muted">
        This is your workspace dashboard. Connect your first Claude in <code className="font-mono text-gold">Chat</code> on the left.
      </p>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { k: "Messages today",  v: "0" },
          { k: "Tasks active",    v: "0" },
          { k: "Memory entries",  v: "0" },
          { k: "Today’s spend",   v: "$0.00" },
        ].map((s) => (
          <div key={s.k} className="rounded-lg border border-border bg-surface p-5 shadow-card">
            <div className="text-xs uppercase tracking-widest text-text-muted">{s.k}</div>
            <div className="mt-2 font-display text-2xl font-semibold">{s.v}</div>
          </div>
        ))}
      </div>

      <div className="mt-10 rounded-lg border border-dashed border-border p-8 text-center">
        <div className="font-semibold mb-1">Phase 1 placeholder</div>
        <div className="text-sm text-text-muted">
          Chat, Tasks, Memory, and Analytics come online in Phase 2. For now, the existing dashboard at{" "}
          <code className="font-mono text-gold">http://localhost:8765</code> is still the live coordination surface.
        </div>
      </div>
    </div>
  )
}

function greet(d: Date): string {
  const h = d.getHours()
  if (h < 5)  return "Up late"
  if (h < 12) return "Good morning"
  if (h < 17) return "Good afternoon"
  return "Good evening"
}
