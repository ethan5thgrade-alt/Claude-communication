import { test } from "node:test";
import assert from "node:assert/strict";
import { parseHTML } from "../src/core/html.ts";
import { parseRobotsTxt, isAllowed } from "../src/core/http.ts";
import { SiteCrawler } from "../src/agents/group02/siteCrawler.ts";
import { HtmlDeepParser } from "../src/agents/group02/htmlParser.ts";
import { TechnicalSEOAuditor } from "../src/agents/group02/technicalAuditor.ts";
import { compare as compareJsSeo } from "../src/agents/group02/jsSeoAnalyzer.ts";
import { estimate as cwvEstimate } from "../src/agents/group02/cwvEstimator.ts";
import { validatePageSchemas } from "../src/agents/group02/schemaInspector.ts";
import { analyzePage as analyzeContent } from "../src/agents/group02/contentQualityAnalyzer.ts";
import { buildGraph } from "../src/agents/group02/architectureMapper.ts";
import { heuristicFingerprint } from "../src/agents/group02/contentFingerprinter.ts";
import { audit as auditRedirects, detectLoops } from "../src/agents/group02/redirectAuditor.ts";

const SAMPLE_HTML = `<!doctype html><html><head>
<title>Pour-over coffee guide</title>
<meta name="description" content="Everything about pour-over coffee.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://coffee.example.com/pour-over">
<link rel="alternate" hreflang="es" href="https://coffee.example.com/es/pour-over">
<script type="application/ld+json">{"@type":"Article","headline":"Pour-over coffee guide","author":"Alex","datePublished":"2026-01-01"}</script>
</head><body>
<h1>Pour-over coffee guide</h1>
<h2>What you need</h2>
<p>A gooseneck kettle, a dripper, filters, fresh beans, and a scale.</p>
<h2>Brew technique</h2>
<p>Bloom for 30 seconds. Pour in slow circles. Total time about three minutes.</p>
<img src="/hero.webp" alt="Pour-over brewing" width="800" height="600" loading="eager">
<img src="/grinder.jpg" alt="Hand grinder" width="400" height="400" loading="lazy">
<a href="/grinders">best grinders</a>
<a href="https://other.example.com/beans">premium beans</a>
<script src="/app.js" defer></script>
</body></html>`;

test("parseHTML extracts core signals", () => {
    const p = parseHTML(SAMPLE_HTML, "https://coffee.example.com/pour-over");
    assert.equal(p.title, "Pour-over coffee guide");
    assert.equal(p.canonical, "https://coffee.example.com/pour-over");
    assert.ok(p.headings.find(h => h.level === 1 && h.text.includes("Pour-over")));
    assert.equal(p.headings.filter(h => h.level === 2).length, 2);
    assert.equal(p.images.length, 2);
    assert.ok(p.images.every(i => i.alt));
    assert.ok(p.links.some(l => l.internal && l.href === "/grinders"));
    assert.ok(p.links.some(l => !l.internal));
    assert.equal(p.schemas.length, 1);
    assert.equal((p.schemas[0].data as { "@type"?: string })?.["@type"], "Article");
});

test("parseRobotsTxt picks Disallow rules", () => {
    const r = parseRobotsTxt(
        ["User-agent: *", "Disallow: /admin", "Disallow: /private", "Crawl-delay: 2"].join("\n"),
        "RankForge",
    );
    assert.deepEqual(r.disallow, ["/admin", "/private"]);
    assert.equal(r.crawl_delay_s, 2);
});

test("isAllowed respects disallow rules", () => {
    const rules = { disallow: ["/admin"], allow: [] };
    assert.equal(isAllowed("https://x.com/admin/users", rules), false);
    assert.equal(isAllowed("https://x.com/blog", rules), true);
});

test("SiteCrawler honors page cap with mock fetcher", async () => {
    let calls = 0;
    const fakePage = (url: string) => Promise.resolve({
        url,
        final_url: url,
        status: 200,
        ok: true,
        redirect_chain: [],
        response_time_ms: 10,
        bytes: 100,
        content_type: "text/html",
        headers: {},
        body: `<a href="${url.endsWith("/") ? url + "p" + (++calls) : url + "/p" + (++calls)}">next</a>`,
    });
    const crawler = new SiteCrawler();
    const out = await crawler.run({
        url: "https://demo.test/",
        max_pages: 5,
        max_depth: 5,
        fetcher: fakePage,
        robots_fetcher: () => Promise.resolve({ disallow: [], allow: [], crawl_delay_s: null, raw: "" }),
    });
    const data = out.data as { page_count: number; hit_cap: boolean };
    assert.equal(out.ok, true);
    assert.equal(data.page_count, 5);
    assert.equal(data.hit_cap, true);
});

test("HtmlDeepParser produces images_with_alt_pct and h1_count", async () => {
    const parser = new HtmlDeepParser();
    const out = await parser.run({
        pages: [{ url: "https://coffee.example.com/pour-over", html: SAMPLE_HTML }],
    });
    const data = out.data as { parsed: { images_with_alt_pct: number; h1_count: number }[] };
    assert.equal(data.parsed[0].h1_count, 1);
    assert.equal(data.parsed[0].images_with_alt_pct, 1);
});

test("TechnicalSEOAuditor scores a clean site high", async () => {
    const parser = new HtmlDeepParser();
    const parseOut = await parser.run({ pages: [{ url: "https://coffee.example.com/", html: SAMPLE_HTML }] });
    const parsed = (parseOut.data as { parsed: unknown[] }).parsed;
    const auditor = new TechnicalSEOAuditor();
    const out = await auditor.run({
        parsed,
        pages: [{ url: "https://coffee.example.com/", final_url: "https://coffee.example.com/",
                  status: 200, depth: 0, response_time_ms: 200, bytes: 100, content_type: "text/html",
                  redirect_chain: [], html_excerpt: SAMPLE_HTML }],
        sitemap_status: 200,
        robots_status: 200,
    });
    const data = out.data as { score: number };
    assert.ok(data.score >= 60, `expected score >= 60 for a clean sample, got ${data.score}`);
});

test("jsSeoAnalyzer flags JS-only content", () => {
    const raw = "<html><body><div id='root'></div></body></html>";
    const rendered = "<html><head><title>App</title></head><body><h1>Hello</h1>" +
        "<p>" + Array(200).fill("real content").join(" ") + "</p>" +
        "<nav><a href='/a'>a</a><a href='/b'>b</a><a href='/c'>c</a><a href='/d'>d</a><a href='/e'>e</a><a href='/f'>f</a></nav>" +
        "</body></html>";
    const r = compareJsSeo(raw, rendered);
    assert.ok(r.findings.some(f => f.toLowerCase().includes("js-rendered")));
    assert.equal(r.js_only_content_risk, "high");
});

test("cwvEstimator grades based on signals", () => {
    const parser = new HtmlDeepParser();
    const p = parser.parseOne("https://x", "https://x", SAMPLE_HTML);
    const est = cwvEstimate(p, 300);
    assert.equal(est.ttfb_grade, "green");
});

test("schemaInspector validates required Article props", () => {
    const parser = new HtmlDeepParser();
    const p = parser.parseOne("https://x", "https://x", SAMPLE_HTML);
    const r = validatePageSchemas(p);
    assert.ok(r.types_present.includes("Article"));
    assert.equal(r.invalid_count, 0);
});

test("schemaInspector flags missing required props", () => {
    const html = `<script type="application/ld+json">{"@type":"Product"}</script>`;
    const parser = new HtmlDeepParser();
    const p = parser.parseOne("https://x", "https://x", html);
    const r = validatePageSchemas(p);
    assert.equal(r.invalid_count, 1);
});

test("contentQualityAnalyzer flags thin content", () => {
    const parser = new HtmlDeepParser();
    const thin = parser.parseOne("https://x/thin", "https://x/thin",
        "<html><body><p>Two words.</p></body></html>");
    const r = analyzeContent(thin, [thin]);
    assert.ok(r.issues.some(i => i.code === "thin_content"));
});

test("architectureMapper builds the link graph", () => {
    const parser = new HtmlDeepParser();
    const home = parser.parseOne("https://x.com/", "https://x.com/",
        `<html><body><a href="/a">A</a><a href="/b">B</a></body></html>`);
    const a = parser.parseOne("https://x.com/a", "https://x.com/a",
        `<html><body><a href="/b">B</a></body></html>`);
    const b = parser.parseOne("https://x.com/b", "https://x.com/b", "<html><body></body></html>");
    const graph = buildGraph([home, a, b], "https://x.com/");
    assert.equal(graph.nodes.length, 3);
    const bNode = graph.nodes.find(n => n.url === "https://x.com/b")!;
    assert.equal(bNode.in_degree, 2);
    assert.equal(bNode.click_depth, 1);
});

test("heuristicFingerprint returns a structured output", () => {
    const parser = new HtmlDeepParser();
    const p = parser.parseOne("https://x", "https://x", SAMPLE_HTML);
    const fp = heuristicFingerprint([p]);
    assert.equal(fp.source, "heuristic");
    assert.ok(fp.primary_niche);
});

test("redirect detectLoops catches a cycle", () => {
    assert.equal(detectLoops([
        { url: "https://a", status: 301 },
        { url: "https://b", status: 301 },
        { url: "https://a", status: 301 },
    ]), true);
});

test("redirectAuditor flags 302 misuse and long chains", () => {
    const pages = [{
        url: "https://x.com/old",
        final_url: "https://x.com/new",
        status: 200,
        depth: 0,
        response_time_ms: 1,
        bytes: 1,
        content_type: "text/html",
        redirect_chain: [
            { url: "https://x.com/old", status: 302 },
            { url: "https://x.com/mid", status: 301 },
        ],
        html_excerpt: "",
    }];
    const parser = new HtmlDeepParser();
    const p = parser.parseOne("https://x.com/new", "https://x.com/new", SAMPLE_HTML);
    const r = auditRedirects(pages, [p]);
    assert.ok(r.misuse_302 >= 1);
    assert.ok(r.fix_map.length >= 1);
});
