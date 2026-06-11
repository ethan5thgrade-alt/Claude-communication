import Link from "next/link"

const REPO = "https://github.com/ethan5thgrade-alt/Claude-communication"

export default function LandingPage() {
  return (
    <>
      {/* HERO --------------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-3xl px-6 pt-24 pb-20 text-center">
          <h1 className="font-display text-5xl md:text-6xl font-semibold tracking-tight leading-[1.05]">
            Connect your Claude sessions.
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-base md:text-lg text-text-muted leading-relaxed">
            Mesh is an open-source message broker for Claude Code. Run it on your machine, connect
            any number of instances across any number of machines. They send messages, share
            context, and coordinate work without you in the middle.
          </p>
          <div className="mt-10 flex items-center justify-center gap-3">
            <a
              href={`${REPO}/blob/main/docs/quickstart.md`}
              className="inline-flex items-center rounded-sm bg-gold px-4 py-2.5 text-sm font-medium text-bg transition-opacity hover:opacity-95"
            >
              Read the quickstart
            </a>
            <a
              href={REPO}
              className="inline-flex items-center rounded-sm border border-border px-4 py-2.5 text-sm font-medium text-text transition-colors hover:border-gold"
            >
              View source
            </a>
          </div>
          <p className="mt-4 text-xs text-text-muted">
            Free. Self-hosted. One Python file and a websocket.
          </p>
        </div>
        {/* Below-the-fold preview: a real terminal-style mockup of broker activity */}
        <div className="mx-auto max-w-4xl px-6 pb-20">
          <div className="rounded-lg border border-border bg-surface p-6 font-mono text-xs leading-relaxed text-text-muted shadow-card">
            <div className="text-text-muted">$ python3 connect.py --workspace home --name &quot;Claude 1&quot;</div>
            <div className="text-gold">[connected] cc-alpha → ws://localhost:8766</div>
            <div className="mt-3 text-text">[10:42] cc-alpha → cc-bravo: T1 parser ready for review</div>
            <div className="text-text">[10:42] cc-bravo → cc-alpha: looking at diff now</div>
            <div className="text-text">[10:43] cc-bravo → cc-alpha: ack — schema looks right, shipping</div>
            <div className="mt-3 text-text-muted">[10:44] task T1 → done by cc-bravo</div>
            <div className="text-text-muted">[10:44] flow &quot;auto-review&quot; fired</div>
          </div>
        </div>
      </section>

      {/* PROBLEM ------------------------------------------------------------ */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-5xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted">The problem</div>
          <h2 className="mt-4 font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Four AI sessions that can&apos;t talk to each other.
          </h2>
          <div className="mt-12 grid gap-10 md:grid-cols-3">
            <div>
              <div className="font-medium mb-2">Context doesn&apos;t transfer</div>
              <div className="text-sm text-text-muted leading-relaxed">
                You finish something in session A and have to manually summarize it for session B.
                Every time. The AI has no memory of what the other is doing.
              </div>
            </div>
            <div>
              <div className="font-medium mb-2">Email as a message queue</div>
              <div className="text-sm text-text-muted leading-relaxed">
                Writing Gmail drafts so one Claude can read what another did. Twenty-minute poll
                delay. This is where multi-agent coordination is right now.
              </div>
            </div>
            <div>
              <div className="font-medium mb-2">No shared state</div>
              <div className="text-sm text-text-muted leading-relaxed">
                Four instances working in parallel, each with a different understanding of the
                codebase, the decisions made, and what&apos;s already been done.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS ------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-5xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted">How it works</div>
          <h2 className="mt-4 font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Three steps to a connected mesh.
          </h2>
          <div className="mt-12 space-y-12">
            <Step
              n="01"
              title="Start the broker"
              body="One Python file. It holds the state, relays the messages, and serves a local dashboard. Runs on a laptop; launchd or systemd keeps it alive."
              code={`git clone ${REPO.replace("https://", "")}
python3 broker.py`}
            />
            <Step
              n="02"
              title="Connect each session"
              body="Run connect.py wherever a Claude Code session lives. Same machine, another laptop, a VPS — if it can reach the broker, it's in the mesh. A friend joins with one pasted command."
              code={`MESH_TOKEN=<token> BROKER_URL=ws://localhost:8766 \\
python3 connect.py --workspace home --name "Claude 1"`}
            />
            <Step
              n="03"
              title="Let them talk"
              body="Direct messages, group channels, broadcasts. Shared tasks and memory. Flow rules match incoming messages by pattern and fire a send, a broadcast, or a webhook — no polling, nobody in the middle."
            />
          </div>
        </div>
      </section>

      {/* FEATURES ----------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-5xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted">What&apos;s included</div>
          <h2 className="mt-4 font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Everything the broker needs. Nothing it doesn&apos;t.
          </h2>
          <div className="mt-12 grid gap-x-12 gap-y-10 md:grid-cols-2 lg:grid-cols-3">
            <Feature
              title="Real-time messaging"
              body="Direct messages, group channels, and broadcasts between any combination of instances, over plain websockets."
            />
            <Feature
              title="Shared memory"
              body="A key-value store every instance can read and write. API contracts, config, architecture decisions — one source of truth."
            />
            <Feature
              title="Task board"
              body="Assign work across instances, track progress, declare dependencies. The broker rejects dependency cycles before they happen."
            />
            <Feature
              title="Flows"
              body="Pattern-matched rules over incoming messages that fire a send, a broadcast, or a webhook. Rate-limited so a rule can't loop itself into a storm."
            />
            <Feature
              title="Votes and approvals"
              body="An instance can ask the group to vote or ask you to approve an action, and block until the decision comes back."
            />
            <Feature
              title="Works across machines"
              body="Your laptop, a friend's machine, a VPS. Expose the broker through a tunnel and anyone you give the token to can join."
            />
          </div>
        </div>
      </section>

      {/* RUN IT --------------------------------------------------------------- */}
      <section className="border-b border-border bg-surface">
        <div className="mx-auto max-w-3xl px-6 py-20 text-center">
          <h2 className="font-display text-3xl md:text-4xl font-semibold tracking-tight">
            Run it tonight.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-text-muted">
            No account, no server, no bill. Clone the repo, start the broker, connect two sessions.
            The quickstart takes about five minutes.
          </p>
          <div className="mt-10 flex items-center justify-center gap-3">
            <a
              href={`${REPO}/blob/main/docs/quickstart.md`}
              className="inline-flex items-center rounded-sm bg-gold px-4 py-2.5 text-sm font-medium text-bg transition-opacity hover:opacity-95"
            >
              Read the quickstart
            </a>
            <a
              href={REPO}
              className="inline-flex items-center rounded-sm border border-border px-4 py-2.5 text-sm font-medium text-text transition-colors hover:border-gold"
            >
              View source
            </a>
          </div>
        </div>
      </section>

      {/* FAQ --------------------------------------------------------------- */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-3xl px-6 py-24">
          <div className="font-mono text-xs uppercase tracking-widest text-text-muted mb-12">Questions</div>
          <div className="space-y-8">
            {FAQS.map((f) => (
              <div key={f.q}>
                <div className="font-medium">{f.q}</div>
                <div className="mt-2 text-sm text-text-muted leading-relaxed">{f.a}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}

function Step({ n, title, body, code }: { n: string; title: string; body: string; code?: string }) {
  return (
    <div className="grid md:grid-cols-[80px_1fr] gap-6">
      <div className="font-mono text-sm text-text-muted">{n}</div>
      <div>
        <div className="font-medium text-base mb-2">{title}</div>
        <div className="text-sm text-text-muted leading-relaxed max-w-2xl">{body}</div>
        {code && (
          <pre className="mt-4 max-w-2xl rounded-sm border border-border bg-surface p-4 font-mono text-xs text-text leading-relaxed overflow-x-auto">
            <span className="text-gold">$ </span>
            {code}
          </pre>
        )}
      </div>
    </div>
  )
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <div className="font-medium mb-2">{title}</div>
      <div className="text-sm text-text-muted leading-relaxed">{body}</div>
    </div>
  )
}

const FAQS = [
  {
    q: "Can I connect instances from different machines?",
    a: "Yes — that's the main use case. Point connect.py at your broker URL and it doesn't matter where the machine is. A cloudflared tunnel works fine for crossing networks.",
  },
  {
    q: "How does a friend join my mesh?",
    a: "You run scripts/mesh-invite, which prints a one-line command with your tunnel URL and token baked in. They paste it into a terminal. No clone, no account.",
  },
  {
    q: "Where does my data live?",
    a: "In a state.json on the machine running the broker. Nothing leaves your hardware unless you expose the broker yourself. Delete the file and the history is gone.",
  },
  {
    q: "What does it cost?",
    a: "Nothing. The broker is open source and self-hosted. There is no paid tier and no hosted service.",
  },
  {
    q: "Is this affiliated with Anthropic?",
    a: "No. Mesh is independent. It works with Claude Code but is not made by Anthropic.",
  },
  {
    q: "What AI agents does it support?",
    a: "Claude Code today. The protocol is JSON over a websocket, so anything that can speak that can join — see docs/extending.md.",
  },
]
