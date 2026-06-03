// Open-redirect guard for the auth callback's attacker-controlled `next` param.
// Kept dependency-free so it can be unit-tested in isolation (no Next runtime).

export const DEFAULT_NEXT = "/onboarding"

// A relative-path allowlist is the only safe input here: the `next` value is
// fully attacker-controlled (it survives the OAuth/email round-trip), so a
// permissive "any same-origin path" check still lets an attacker land a victim
// on an arbitrary internal route post-login. We instead match the actual route
// surface and reject everything else.
//
// Slugs follow the workspace `slug` shape (lowercase alphanumeric + hyphen).
const SLUG = "[a-z0-9]+(?:-[a-z0-9]+)*"

// Invite tokens are mixed/uppercase alphanumeric (generated via rand() over
// [A-Z0-9]); they are NOT slugs, so they need their own class or /invite/<TOKEN>
// links are wrongly rejected and invite signups never round-trip back.
const TOKEN = "[A-Za-z0-9]+"

// Known in-app sub-pages under /[workspaceSlug]. A bare /<workspaceSlug> is NOT
// allowed because it is indistinguishable from a stray route; real workspace
// links always carry a sub-page.
const WORKSPACE_SUBPAGES = [
  "tasks",
  "memory",
  "chat",
  "votes",
  "automations",
  "approvals",
  "channels",
  "analytics",
] as const

// Allowed destinations, anchored on the PATH only (query/fragment are stripped
// before matching, see below). Each alternative covers a real route:
//   /onboarding, /onboarding/invite, /onboarding/connect
//   /settings
//   /invite/<token>
//   /<workspaceSlug>/<knownSubpage>[/...]
const ALLOWED = new RegExp(
  "^/(?:" +
    [
      "onboarding(?:/(?:invite|connect))?",
      "settings",
      `invite/${TOKEN}`,
      `${SLUG}/(?:${WORKSPACE_SUBPAGES.join("|")})(?:/[A-Za-z0-9._~-]+)*`,
    ].join("|") +
    ")$",
)

export function safeNextPath(raw: string | null | undefined): string {
  if (!raw) return DEFAULT_NEXT
  // Backslashes are never valid in a real path and some browsers normalise them
  // to "/", which would let "/\attacker.com" smuggle past the anchored regex.
  // Reject them outright before any further parsing.
  if (raw.includes("\\")) return DEFAULT_NEXT
  // Split off the query string and fragment so the allowlist matches the route
  // path alone. The suffix is re-attached on success, so a legitimate deep link
  // like "/settings?tab=billing" is preserved verbatim. The suffix cannot widen
  // the open-redirect surface: the path is confirmed same-origin first, and a
  // query/fragment on a same-origin relative path stays on-origin when resolved
  // against url.origin in the callback route.
  const suffixStart = (() => {
    const q = raw.indexOf("?")
    const h = raw.indexOf("#")
    if (q === -1) return h
    if (h === -1) return q
    return Math.min(q, h)
  })()
  const path = suffixStart === -1 ? raw : raw.slice(0, suffixStart)
  if (!ALLOWED.test(path)) return DEFAULT_NEXT
  return raw
}
