// Mesh brand mark — 4 dots connected by lines (4 Claudes working together).
// Inherits color; pass `className` for size + color tweaks.
export function Logo({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <circle cx="3"  cy="3"  r="2"   fill="currentColor" />
      <circle cx="13" cy="3"  r="2"   fill="currentColor" opacity="0.7" />
      <circle cx="8"  cy="8"  r="2.4" fill="currentColor" />
      <circle cx="3"  cy="13" r="2"   fill="currentColor" opacity="0.7" />
      <circle cx="13" cy="13" r="2"   fill="currentColor" />
      <path
        d="M3 3 L8 8 L13 3 M3 13 L8 8 L13 13"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.55"
      />
    </svg>
  )
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <div className={`inline-flex items-center gap-2 font-display text-text ${className}`}>
      <Logo className="h-5 w-5 text-gold" />
      <span className="font-semibold tracking-tight">Mesh</span>
    </div>
  )
}
