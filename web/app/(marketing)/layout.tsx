import Link from "next/link"
import { Wordmark } from "@/components/shared/Logo"

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Link href="/" aria-label="Mesh home">
            <Wordmark />
          </Link>
          <nav className="flex items-center gap-2 text-sm text-text-muted">
            <Link href="/pricing" className="px-3 py-2 hover:text-text transition-colors">Pricing</Link>
            <Link href="/blog"    className="px-3 py-2 hover:text-text transition-colors">Blog</Link>
            <Link href="/login"   className="px-3 py-2 hover:text-text transition-colors">Log in</Link>
            <Link
              href="/signup"
              className="ml-2 inline-flex items-center rounded-full bg-gold px-4 py-2 text-sm font-semibold text-bg hover:bg-gold-bright transition-colors"
            >
              Start free
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-border py-10 text-sm text-text-muted">
        <div className="mx-auto max-w-6xl px-6 flex flex-wrap items-center justify-between gap-4">
          <div>© {new Date().getFullYear()} Mesh — Made for developers who take AI seriously.</div>
          <div className="flex gap-5">
            <Link href="/privacy" className="hover:text-text">Privacy</Link>
            <Link href="/terms"   className="hover:text-text">Terms</Link>
            <a href="https://github.com/ethan5thgrade-alt/Claude-communication" className="hover:text-text">GitHub</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
