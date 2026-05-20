// 011 — Site Crawler.
// BFS crawl up to N pages, depth-capped, robots.txt-aware.

import { AgentBase } from "../../core/AgentBase.ts";
import { fetchPage, fetchRobots, isAllowed, type FetchedPage } from "../../core/http.ts";
import { parseHTML } from "../../core/html.ts";
import type { AgentInput, AgentOutput, PlanTier } from "../../core/types.ts";

export const PAGE_CAP_BY_PLAN: Record<PlanTier, number> = {
    free: 25,
    starter: 50,
    pro: 100,
    agency: 100,
};
export const MAX_DEPTH = 3;

export interface CrawledPage {
    url: string;
    final_url: string;
    status: number;
    depth: number;
    response_time_ms: number;
    bytes: number;
    content_type: string;
    redirect_chain: { url: string; status: number }[];
    html_excerpt: string;
}

function normalize(href: string, base: string): string | null {
    try {
        const u = new URL(href, base);
        u.hash = "";
        return u.href;
    } catch {
        return null;
    }
}

export class SiteCrawler extends AgentBase {
    readonly id = "site_crawler";
    readonly name = "Site Crawler";
    readonly group = 2;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const startUrl = (input.url as string | undefined)
            ?? (typeof input.site === "object" ? (input.site as { url?: string })?.url : undefined);
        if (!startUrl) return { ok: false, error: "url required" };
        const plan = ((input.plan as PlanTier | undefined) ?? "free");
        const pageCap = (input.max_pages as number | undefined) ?? PAGE_CAP_BY_PLAN[plan];
        const maxDepth = (input.max_depth as number | undefined) ?? MAX_DEPTH;
        const fetcher = (input.fetcher as ((u: string) => Promise<FetchedPage>) | undefined) ?? fetchPage;
        const robotsFetcher = (input.robots_fetcher as (typeof fetchRobots) | undefined) ?? fetchRobots;

        const robots = await robotsFetcher(startUrl);
        const sameHost = new URL(startUrl).host;

        const queue: { url: string; depth: number }[] = [{ url: startUrl, depth: 0 }];
        const seen = new Set<string>();
        const pages: CrawledPage[] = [];
        const blocked: string[] = [];

        while (queue.length && pages.length < pageCap) {
            const { url, depth } = queue.shift()!;
            if (seen.has(url)) continue;
            seen.add(url);

            if (!isAllowed(url, robots)) {
                blocked.push(url);
                continue;
            }

            const r = await fetcher(url);
            const page: CrawledPage = {
                url: r.url,
                final_url: r.final_url,
                status: r.status,
                depth,
                response_time_ms: r.response_time_ms,
                bytes: r.bytes,
                content_type: r.content_type,
                redirect_chain: r.redirect_chain,
                html_excerpt: r.body.slice(0, 4000),
            };
            pages.push(page);

            if (depth >= maxDepth) continue;
            if (!r.body) continue;
            const parsed = parseHTML(r.body, r.final_url);
            for (const link of parsed.links) {
                if (!link.internal) continue;
                if ((link.rel ?? "").toLowerCase().includes("nofollow")) continue;
                const norm = normalize(link.href, r.final_url);
                if (!norm) continue;
                if (!norm.startsWith("http")) continue;
                if (new URL(norm).host !== sameHost) continue;
                if (seen.has(norm)) continue;
                queue.push({ url: norm, depth: depth + 1 });
            }

            // crawl-delay: respect if set
            if (robots.crawl_delay_s && robots.crawl_delay_s > 0) {
                await this.sleep(robots.crawl_delay_s * 1000);
            }

            // Progress emit every 5 pages
            if (pages.length % 5 === 0) {
                await this.emit("crawl_progress", { url: startUrl, pages_done: pages.length, queue_size: queue.length });
            }
        }

        return {
            ok: true,
            data: {
                start_url: startUrl,
                pages,
                blocked_by_robots: blocked,
                page_count: pages.length,
                hit_cap: pages.length >= pageCap,
            },
        };
    }
}
