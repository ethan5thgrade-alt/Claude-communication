import { redirect, notFound } from "next/navigation"
import { createClient } from "@/lib/supabase/server"
import { AppSidebar } from "@/components/app/AppSidebar"

export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: { workspaceSlug: string }
}) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const { data: workspace } = await supabase
    .from("workspaces")
    .select("id, slug, name, plan, owner_id")
    .eq("slug", params.workspaceSlug)
    .single()
  if (!workspace) notFound()

  // Membership check (RLS would also block, but a clean 404 is friendlier).
  const { data: member } = await supabase
    .from("workspace_members")
    .select("role")
    .eq("workspace_id", workspace.id)
    .eq("user_id", user.id)
    .single()
  if (!member) notFound()

  return (
    <div className="flex h-screen bg-bg">
      <AppSidebar workspace={workspace} />
      <div className="flex-1 overflow-y-auto">{children}</div>
    </div>
  )
}
