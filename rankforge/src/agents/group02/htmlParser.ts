// 012 — HTML Deep Parser.
// Per-page extraction of every signal we use downstream.

import { AgentBase } from "../../core/AgentBase.ts";
import { parseHTML, type ParsedHTML } from "../../core/html.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export interface ParsedPage extends ParsedHTML {
    url: string;
    final_url: string;
    images_with_alt_pct: number;
    render_blocking_scripts: number;
    h1_count: number;
}

export class HtmlDeepParser extends AgentBase {
    readonly id = "html_parser";
    readonly name = "HTML Deep Parser";
    readonly group = 2;
    readonly version = "1.0.0";

    parseOne(url: string, finalUrl: string, html: string): ParsedPage {
        const p = parseHTML(html, finalUrl || url);
        const totalImages = p.images.length || 1;
        const withAlt = p.images.filter(i => i.alt && i.alt.trim()).length;
        const renderBlocking = p.scripts.filter(s => !s.async && !s.defer && s.src).length;
        const h1Count = p.headings.filter(h => h.level === 1).length;
        return {
            ...p,
            url,
            final_url: finalUrl || url,
            images_with_alt_pct: withAlt / totalImages,
            render_blocking_scripts: renderBlocking,
            h1_count: h1Count,
        };
    }

    async run(input: AgentInput): Promise<AgentOutput> {
        // input.pages: [{url, final_url, html}] or input.html + input.url
        const pages = (input.pages as { url: string; final_url?: string; html: string }[] | undefined)
            ?? (input.html ? [{ url: input.url as string, final_url: input.url as string, html: input.html as string }] : []);
        if (pages.length === 0) return { ok: false, error: "no pages to parse" };
        const out = pages.map(p => this.parseOne(p.url, p.final_url ?? p.url, p.html));
        return { ok: true, data: { parsed: out, count: out.length } };
    }
}
