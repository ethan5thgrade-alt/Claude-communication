// Shared HTTP helper used by the Group-2 crawlers. Wraps native fetch with:
//   - a deadline (default 15s)
//   - User-Agent identifying RankForge
//   - capturing redirect chain + final URL + status + headers + body
//   - bytes-cap to defend against infinite responses
//
// Pure Node built-ins. No external deps.

export interface FetchedPage {
    url: string;                  // requested URL
    final_url: string;            // after redirects
    status: number;
    ok: boolean;
    redirect_chain: { url: string; status: number }[];
    response_time_ms: number;
    bytes: number;
    content_type: string;
    headers: Record<string, string>;
    body: string;                 // may be truncated to MAX_BYTES
    error?: string;
}

export const DEFAULT_TIMEOUT_MS = 15_000;
export const MAX_BYTES = 5 * 1024 * 1024;  // 5MB

export async function fetchPage(url: string, opts: { timeoutMs?: number; userAgent?: string } = {}): Promise<FetchedPage> {
    const started = Date.now();
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
    const ua = opts.userAgent ?? "Mozilla/5.0 (compatible; RankForge/0.1; +https://github.com/ethan5thgrade-alt/Claude-communication)";

    const chain: { url: string; status: number }[] = [];

    try {
        // Native fetch follows redirects but doesn't expose the chain. So we
        // walk manually with redirect: "manual" up to 10 hops.
        let current = url;
        let resp: Response | null = null;
        for (let hop = 0; hop < 10; hop++) {
            resp = await fetch(current, {
                redirect: "manual",
                signal: ctrl.signal,
                headers: { "User-Agent": ua, "Accept": "text/html,*/*" },
            });
            if (resp.status >= 300 && resp.status < 400) {
                const loc = resp.headers.get("location");
                if (!loc) break;
                chain.push({ url: current, status: resp.status });
                current = new URL(loc, current).href;
                continue;
            }
            break;
        }
        if (!resp) throw new Error("no response");

        // Stream-read but cap at MAX_BYTES
        const reader = resp.body?.getReader();
        let bytes = 0;
        let chunks: Uint8Array[] = [];
        if (reader) {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                if (value) {
                    bytes += value.byteLength;
                    if (bytes > MAX_BYTES) {
                        try { await reader.cancel(); } catch { /* ignore */ }
                        break;
                    }
                    chunks.push(value);
                }
            }
        }
        const buf = Buffer.concat(chunks.map(c => Buffer.from(c)));
        const body = buf.toString("utf-8");

        const headers: Record<string, string> = {};
        resp.headers.forEach((v, k) => { headers[k] = v; });

        return {
            url,
            final_url: current,
            status: resp.status,
            ok: resp.ok,
            redirect_chain: chain,
            response_time_ms: Date.now() - started,
            bytes,
            content_type: headers["content-type"] ?? "",
            headers,
            body,
        };
    } catch (err) {
        return {
            url,
            final_url: url,
            status: 0,
            ok: false,
            redirect_chain: chain,
            response_time_ms: Date.now() - started,
            bytes: 0,
            content_type: "",
            headers: {},
            body: "",
            error: (err as Error).message,
        };
    } finally {
        clearTimeout(t);
    }
}

/** Fetch a robots.txt-style file and parse the allow/disallow rules + crawl-delay. */
export async function fetchRobots(originUrl: string, userAgent: string = "RankForge"): Promise<{
    disallow: string[];
    allow: string[];
    crawl_delay_s: number | null;
    raw: string;
}> {
    let robotsUrl = "";
    try { robotsUrl = new URL("/robots.txt", originUrl).href; } catch { /* invalid */ }
    if (!robotsUrl) return { disallow: [], allow: [], crawl_delay_s: null, raw: "" };
    const r = await fetchPage(robotsUrl, { timeoutMs: 5000 });
    if (!r.ok) return { disallow: [], allow: [], crawl_delay_s: null, raw: "" };
    return { ...parseRobotsTxt(r.body, userAgent), raw: r.body };
}

export function parseRobotsTxt(raw: string, userAgent: string): {
    disallow: string[]; allow: string[]; crawl_delay_s: number | null;
} {
    const lines = raw.split("\n").map(l => l.replace(/#.*$/, "").trim()).filter(Boolean);
    const disallow: string[] = [];
    const allow: string[] = [];
    let delay: number | null = null;
    let active = false;
    const want = userAgent.toLowerCase();
    for (const line of lines) {
        const [rawKey, ...rest] = line.split(":");
        if (!rawKey || rest.length === 0) continue;
        const key = rawKey.toLowerCase().trim();
        const val = rest.join(":").trim();
        if (key === "user-agent") {
            active = val === "*" || val.toLowerCase() === want;
        } else if (active) {
            if (key === "disallow" && val) disallow.push(val);
            if (key === "allow" && val) allow.push(val);
            if (key === "crawl-delay") {
                const n = Number(val);
                if (!Number.isNaN(n)) delay = n;
            }
        }
    }
    return { disallow, allow, crawl_delay_s: delay };
}

/** Returns true if URL path is blocked by the disallow rules. */
export function isAllowed(url: string, rules: { disallow: string[]; allow: string[] }): boolean {
    let path = "";
    try { path = new URL(url).pathname + new URL(url).search; } catch { return true; }
    // Allow rules take precedence
    if (rules.allow.some(p => path.startsWith(p))) return true;
    if (rules.disallow.some(p => path.startsWith(p))) return false;
    return true;
}
