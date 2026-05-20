"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { Logo } from "@/components/shared/Logo"
import { Home, MessageSquare, ListChecks, Brain, Zap, BarChart3, Settings } from "lucide-react"

const NAV = [
  { href: "",            label: "Home",        icon: Home },
  { href: "/chat",       label: "Chat",        icon: MessageSquare },
  { href: "/tasks",      label: "Tasks",       icon: ListChecks },
  { href: "/memory",     label: "Memory",      icon: Brain },
  { href: "/automations",label: "Automations", icon: Zap },
  { href: "/analytics",  label: "Analytics",   icon: BarChart3 },
]

export function AppSidebar({ workspace }: { workspace: { slug: string; name: string; plan: string } }) {
  const pathname = usePathname()
  const base = `/${workspace.slug}`

  return (
    <aside className="flex h-screen w-60 flex-col border-r border-border bg-surface">
      <div className="border-b border-border px-4 py-4">
        <Link href={base} className="inline-flex items-center gap-2 text-text">
          <Logo className="h-5 w-5 text-gold" />
          <span className="font-display text-base font-semibold tracking-tight">{workspace.name}</span>
        </Link>
        <div className="mt-1 text-xs text-text-muted capitalize">{workspace.plan} plan</div>
      </div>
      <nav className="flex-1 overflow-y-auto p-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const url = base + href
          const active = pathname === url || (href && pathname.startsWith(url))
          return (
            <Link key={label} href={url}
              className={cn(
                "flex items-center gap-3 rounded-sm px-3 py-2 text-sm transition-colors",
                active ? "bg-[color:var(--gold-tint)] text-gold" : "text-text-muted hover:text-text hover:bg-bg",
              )}>
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          )
        })}
      </nav>
      <div className="border-t border-border p-3">
        <Link href={`${base}/settings`}
          className="flex items-center gap-2 rounded-sm px-2 py-2 text-sm text-text-muted hover:text-text hover:bg-bg">
          <Settings className="h-4 w-4" /> Settings
        </Link>
      </div>
    </aside>
  )
}
