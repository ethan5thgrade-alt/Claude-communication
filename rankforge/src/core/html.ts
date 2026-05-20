// Tiny dependency-free HTML extractor.
// Just enough to feed the Group 2 SEO agents. Not a full DOM — uses regex.
// Robust enough for typical CMS output; falls back gracefully on weird HTML.

export interface MetaTag { name?: string; property?: string; httpEquiv?: string; content?: string }
export interface Heading { level: 1 | 2 | 3 | 4 | 5 | 6; text: string; depth: number }
export interface ImageRef { src: string; alt: string; width?: string; height?: string; loading?: string }
export interface LinkRef { href: string; anchor: string; rel: string; internal: boolean }
export interface SchemaBlock { format: "json-ld" | "microdata"; type?: string; raw: string; data?: unknown }
export interface ScriptRef { src?: string; async: boolean; defer: boolean; inline?: boolean }
export interface ParsedHTML {
    title: string;
    metas: MetaTag[];
    canonical: string | null;
    hreflang: { lang: string; href: string }[];
    headings: Heading[];
    images: ImageRef[];
    links: LinkRef[];
    schemas: SchemaBlock[];
    scripts: ScriptRef[];
    word_count: number;
    paragraph_count: number;
    sentence_count: number;
    avg_sentence_length: number;
    reading_level: number;        // Flesch-Kincaid grade level
    hidden_content_flags: number; // count of display:none / visibility:hidden patterns
    inline_styles_chars: number;
    external_stylesheets: number;
    text_excerpt: string;
}

function findAll(re: RegExp, s: string): RegExpExecArray[] {
    const out: RegExpExecArray[] = [];
    let m: RegExpExecArray | null;
    const r = new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
    while ((m = r.exec(s)) !== null) out.push(m);
    return out;
}

function getAttr(tag: string, name: string): string | undefined {
    const m = tag.match(new RegExp(`${name}\\s*=\\s*"([^"]*)"`, "i"))
        ?? tag.match(new RegExp(`${name}\\s*=\\s*'([^']*)'`, "i"))
        ?? tag.match(new RegExp(`${name}\\s*=\\s*([^\\s>]+)`, "i"));
    return m?.[1];
}

function stripTags(html: string): string {
    return html
        .replace(/<script[\s\S]*?<\/script>/gi, " ")
        .replace(/<style[\s\S]*?<\/style>/gi, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}

function countSyllables(word: string): number {
    word = word.toLowerCase().replace(/[^a-z]/g, "");
    if (!word) return 0;
    if (word.length <= 3) return 1;
    const m = word.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, "").match(/[aeiouy]{1,2}/g);
    return m?.length ?? 1;
}

function fleschKincaid(text: string): { sentences: number; words: number; grade: number } {
    const sentences = (text.match(/[.!?]+/g) ?? []).length || 1;
    const words = text.split(/\s+/).filter(w => /[a-zA-Z]/.test(w));
    const wordCount = words.length || 1;
    const syllables = words.reduce((s, w) => s + countSyllables(w), 0);
    const grade = 0.39 * (wordCount / sentences) + 11.8 * (syllables / wordCount) - 15.59;
    return { sentences, words: wordCount, grade: Math.max(0, grade) };
}

export function parseHTML(html: string, pageUrl: string = ""): ParsedHTML {
    const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    const title = titleMatch ? titleMatch[1].trim() : "";

    const metas: MetaTag[] = findAll(/<meta\b[^>]*>/gi, html).map(m => {
        const tag = m[0];
        return {
            name: getAttr(tag, "name"),
            property: getAttr(tag, "property"),
            httpEquiv: getAttr(tag, "http-equiv"),
            content: getAttr(tag, "content"),
        };
    });

    const canonicalMatch = html.match(/<link\b[^>]*\brel\s*=\s*["']?canonical["']?[^>]*>/i);
    const canonical = canonicalMatch ? (getAttr(canonicalMatch[0], "href") ?? null) : null;

    const hreflang: { lang: string; href: string }[] = findAll(
        /<link\b[^>]*\bhreflang\s*=\s*["']([^"']+)["'][^>]*>/gi, html,
    ).map(m => ({
        lang: m[1],
        href: getAttr(m[0], "href") ?? "",
    }));

    const headings: Heading[] = [];
    for (const level of [1, 2, 3, 4, 5, 6] as const) {
        for (const m of findAll(new RegExp(`<h${level}\\b[^>]*>([\\s\\S]*?)<\\/h${level}>`, "gi"), html)) {
            headings.push({ level, text: stripTags(m[1]), depth: level });
        }
    }

    const images: ImageRef[] = findAll(/<img\b[^>]*>/gi, html).map(m => ({
        src: getAttr(m[0], "src") ?? "",
        alt: getAttr(m[0], "alt") ?? "",
        width: getAttr(m[0], "width"),
        height: getAttr(m[0], "height"),
        loading: getAttr(m[0], "loading"),
    }));

    const sameHost = (() => {
        try { return new URL(pageUrl).host; } catch { return ""; }
    })();
    const links: LinkRef[] = findAll(/<a\b[^>]*\bhref\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi, html)
        .map(m => {
            const href = m[1];
            const rel = getAttr(m[0], "rel") ?? "";
            let internal = false;
            try {
                if (href.startsWith("/")) internal = true;
                else if (href.startsWith("#")) internal = true;
                else if (sameHost && new URL(href).host === sameHost) internal = true;
            } catch { /* invalid url */ }
            return { href, anchor: stripTags(m[2]), rel, internal };
        });

    // JSON-LD schemas
    const schemas: SchemaBlock[] = findAll(
        /<script\b[^>]*\btype\s*=\s*["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi, html,
    ).map(m => {
        const raw = m[1].trim();
        let data: unknown;
        try { data = JSON.parse(raw); } catch { /* invalid */ }
        const type = (data as { "@type"?: string })?.["@type"];
        return { format: "json-ld" as const, type, raw, data };
    });

    // Microdata (lightweight: just count itemtype occurrences)
    for (const m of findAll(/itemtype\s*=\s*["']([^"']+)["']/gi, html)) {
        schemas.push({ format: "microdata", type: m[1].split("/").pop() ?? m[1], raw: m[0] });
    }

    const scripts: ScriptRef[] = findAll(/<script\b[^>]*>/gi, html).map(m => ({
        src: getAttr(m[0], "src"),
        async: /\basync\b/i.test(m[0]),
        defer: /\bdefer\b/i.test(m[0]),
        inline: !getAttr(m[0], "src"),
    }));

    const externalStylesheets = findAll(/<link\b[^>]*\brel\s*=\s*["']?stylesheet["']?/gi, html).length;
    const inlineStylesChars = (html.match(/<style\b[^>]*>([\s\S]*?)<\/style>/gi) ?? [])
        .reduce((s, b) => s + b.length, 0);

    const visibleText = stripTags(html);
    const fk = fleschKincaid(visibleText);
    const paragraphs = (html.match(/<p\b[^>]*>/gi) ?? []).length;

    const hiddenContentFlags =
        (html.match(/display\s*:\s*none/gi) ?? []).length
        + (html.match(/visibility\s*:\s*hidden/gi) ?? []).length;

    return {
        title,
        metas,
        canonical,
        hreflang,
        headings,
        images,
        links,
        schemas,
        scripts,
        word_count: fk.words,
        paragraph_count: paragraphs,
        sentence_count: fk.sentences,
        avg_sentence_length: fk.words / Math.max(fk.sentences, 1),
        reading_level: fk.grade,
        hidden_content_flags: hiddenContentFlags,
        inline_styles_chars: inlineStylesChars,
        external_stylesheets: externalStylesheets,
        text_excerpt: visibleText.slice(0, 800),
    };
}
