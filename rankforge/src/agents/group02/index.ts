// Group 2 — Crawl & Deep Analysis.

import { AgentBase } from "../../core/AgentBase.ts";
import { registerAgent } from "../../core/registry.ts";
import { SiteCrawler } from "./siteCrawler.ts";
import { HtmlDeepParser } from "./htmlParser.ts";
import { TechnicalSEOAuditor } from "./technicalAuditor.ts";
import { JsSeoAnalyzer } from "./jsSeoAnalyzer.ts";
import { CwvEstimator } from "./cwvEstimator.ts";
import { SchemaInspector } from "./schemaInspector.ts";
import { ContentQualityAnalyzer } from "./contentQualityAnalyzer.ts";
import { CompetitorIntel } from "./competitorIntel.ts";
import { ArchitectureMapper } from "./architectureMapper.ts";
import { ContentFingerprinter } from "./contentFingerprinter.ts";
import { SpeedAuditor } from "./speedAuditor.ts";
import { RedirectAuditor } from "./redirectAuditor.ts";

export * from "./siteCrawler.ts";
export * from "./htmlParser.ts";
export * from "./technicalAuditor.ts";
export * from "./jsSeoAnalyzer.ts";
export * from "./cwvEstimator.ts";
export * from "./schemaInspector.ts";
export * from "./contentQualityAnalyzer.ts";
export * from "./competitorIntel.ts";
export * from "./architectureMapper.ts";
export * from "./contentFingerprinter.ts";
export * from "./speedAuditor.ts";
export * from "./redirectAuditor.ts";

export function registerGroup02(): Record<string, AgentBase> {
    const all: Record<string, AgentBase> = {
        site_crawler: new SiteCrawler(),
        html_parser: new HtmlDeepParser(),
        technical_auditor: new TechnicalSEOAuditor(),
        js_seo_analyzer: new JsSeoAnalyzer(),
        cwv_estimator: new CwvEstimator(),
        schema_inspector: new SchemaInspector(),
        content_quality: new ContentQualityAnalyzer(),
        competitor_intel: new CompetitorIntel(),
        architecture_mapper: new ArchitectureMapper(),
        content_fingerprinter: new ContentFingerprinter(),
        speed_auditor: new SpeedAuditor(),
        redirect_auditor: new RedirectAuditor(),
    };
    for (const a of Object.values(all)) registerAgent(a);
    return all;
}
