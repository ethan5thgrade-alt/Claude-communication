import Link from "next/link"
import { Wordmark } from "@/components/shared/Logo"

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Link href="/" aria-label="Mesh home">
            <Wordmark />
          </Link>
          <nav className="flex items-center gap-1 text-sm text-text-muted">
            <Link href="/docs"       className="px-3 py-2 hover:text-text transition-colors">Docs</Link>
            <Link href="/changelog"  className="px-3 py-2 hover:text-text transition-colors">Changelog</Link>
            <a href="https://github.com/ethan5thgrade-alt/Claude-communication"
               className="px-3 py-2 hover:text-text transition-colors">GitHub</a>
            <Link href="/login"      className="px-3 py-2 hover:text-text transition-colors">Log in</Link>
            <Link
              href="/signup"
              className="ml-2 inline-flex items-center rounded-sm border border-gold px-3 py-1.5 text-sm text-gold hover:bg-gold hover:text-bg transition-colors"
            >
              Sign up
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-border py-12 text-sm text-text-muted">
        <div className="mx-auto grid max-w-6xl px-6 gap-10 md:grid-cols-3">
          <FooterCol heading="Product" links={[
            ["Dashboard", "/login"], ["Changelog", "/changelog"],
          ]}/>
          <FooterCol heading="Docs" links={[
            ["Getting started", "/docs"],
            ["Quickstart", "https://github.com/ethan5thgrade-alt/Claude-communication/blob/main/docs/quickstart.md"],
            ["Architecture", "https://github.com/ethan5thgrade-alt/Claude-communication/blob/main/docs/architecture.md"],
            ["Security", "https://github.com/ethan5thgrade-alt/Claude-communication/blob/main/docs/security.md"],
          ]}/>
          <FooterCol heading="Links" links={[
            ["GitHub", "https://github.com/ethan5thgrade-alt/Claude-communication"],
          ]}/>
        </div>
        <div className="mx-auto mt-12 max-w-6xl px-6 text-xs text-text-muted">
          <span className="font-mono">mesh — open source, self-hosted</span>
        </div>
      </footer>
    </div>
  )
}

function FooterCol({ heading, links }: { heading: string; links: [string, string][] }) {
  return (
    <div>
      <div className="font-mono text-xs uppercase tracking-widest text-text-muted mb-3">{heading}</div>
      <ul className="space-y-2">
        {links.map(([label, href]) => (
          <li key={label}>
            <Link href={href} className="text-text hover:text-text-muted transition-colors">{label}</Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
