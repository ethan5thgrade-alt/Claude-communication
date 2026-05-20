// Mesh brand mark — 4 dots in a 2x2 grid, connected by thin lines.
// Monochrome, no gradient. Works at 16px. Inherits text color.
export function Logo({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M4 4 L12 4 L12 12 L4 12 Z M4 4 L12 12 M12 4 L4 12"
        stroke="currentColor"
        strokeWidth="0.75"
        opacity="0.45"
        strokeLinecap="round"
      />
      <circle cx="4"  cy="4"  r="1.6" fill="currentColor" />
      <circle cx="12" cy="4"  r="1.6" fill="currentColor" />
      <circle cx="4"  cy="12" r="1.6" fill="currentColor" />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" />
    </svg>
  )
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <div className={`inline-flex items-center gap-2 font-display text-text ${className}`}>
      <Logo className="h-4 w-4 text-text" />
      <span className="font-semibold tracking-tight lowercase">mesh</span>
    </div>
  )
}
