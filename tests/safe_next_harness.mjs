/**
 * Test harness for the auth-callback open-redirect guard.
 *
 * Drives the REAL safeNextPath from web/lib/safe-next.ts (the same function the
 * callback route imports) so the redirect contract is verified against shipping
 * code, not a copy. Node 22+ strips the TS types on import.
 *
 * Invocation (env-driven so empty-string vs absent stays unambiguous):
 *   NEXT_PRESENT=1 NEXT_INPUT='https://attacker.com' \
 *   node --experimental-strip-types tests/safe_next_harness.mjs
 *
 * NEXT_PRESENT unset -> safeNextPath is called with null (param absent).
 * Prints exactly one JSON line: {"ok": true, "result": "<resolved path>"}.
 */
import { safeNextPath } from "../web/lib/safe-next.ts";

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

try {
  const present = process.env.NEXT_PRESENT === "1";
  const input = present ? (process.env.NEXT_INPUT ?? "") : null;
  emit({ ok: true, result: safeNextPath(input) });
} catch (err) {
  emit({ ok: false, error: String((err && err.message) || err) });
  process.exit(1);
}
