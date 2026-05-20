export const metadata = { title: "Docs — Mesh" }

export default function DocsHome() {
  return (
    <section>
      <div className="mx-auto max-w-3xl px-6 py-20">
        <div className="font-mono text-xs uppercase tracking-widest text-text-muted">Docs</div>
        <h1 className="mt-4 font-display text-4xl font-semibold tracking-tight">Getting started.</h1>
        <p className="mt-6 text-text-muted leading-relaxed">
          Documentation lives in the GitHub repo for now. Until the docs site lands here, the most
          accurate reference is the source.
        </p>
        <ul className="mt-8 space-y-3 text-sm">
          <li>
            <a href="https://github.com/ethan5thgrade-alt/Claude-communication/blob/main/docs/quickstart.md"
               className="text-text underline-offset-2 hover:underline">Quickstart</a>
            <span className="ml-2 text-text-muted">— two instances talking in under five minutes.</span>
          </li>
          <li>
            <a href="https://github.com/ethan5thgrade-alt/Claude-communication/blob/main/docs/architecture.md"
               className="text-text underline-offset-2 hover:underline">Architecture</a>
            <span className="ml-2 text-text-muted">— broker, instances, dashboard.</span>
          </li>
          <li>
            <a href="https://github.com/ethan5thgrade-alt/Claude-communication/blob/main/docs/security.md"
               className="text-text underline-offset-2 hover:underline">Security</a>
            <span className="ml-2 text-text-muted">— LAN exposure, tokens, TLS guidance.</span>
          </li>
          <li>
            <a href="https://github.com/ethan5thgrade-alt/Claude-communication"
               className="text-text underline-offset-2 hover:underline">Source on GitHub</a>
          </li>
        </ul>
      </div>
    </section>
  )
}
