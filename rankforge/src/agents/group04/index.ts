// Group 4 — Content Creation Engine (agents 039-049, partial).
// Coder 1 owns 039-044 (planner + 5 writers).
// Coder 2 owns 045-049 (faq, case study, press release, email, video script).

import { AgentBase } from "../../core/AgentBase.ts";
import { registerAgent } from "../../core/registry.ts";

import { ContentPlanner } from "./contentPlanner.ts";
import { BlogWriter } from "./blogWriter.ts";
import { HowtoWriter } from "./howtoWriter.ts";
import { ListicleWriter } from "./listicleWriter.ts";
import { ComparisonWriter } from "./comparisonWriter.ts";
import { LocalPageWriter } from "./localPageWriter.ts";

import { FaqArticleWriter } from "./faqArticleWriter.ts";
import { CaseStudyWriter } from "./caseStudyWriter.ts";
import { PressReleaseWriter } from "./pressReleaseWriter.ts";
import { EmailWriter } from "./emailWriter.ts";
import { VideoScriptWriter } from "./videoScriptWriter.ts";

export {
    ContentPlanner,
    type PlannerCluster,
    type ContentBrief,
} from "./contentPlanner.ts";
export { BlogWriter, type BlogInput, defaultBlogTemplate } from "./blogWriter.ts";
export { HowtoWriter, type HowtoInput, type HowtoStep, defaultHowtoTemplate } from "./howtoWriter.ts";
export { ListicleWriter, type ListicleInput, type ListicleItem, defaultListicleTemplate } from "./listicleWriter.ts";
export { ComparisonWriter, type ComparisonInput, type ComparisonOption, defaultComparisonTemplate } from "./comparisonWriter.ts";
export { LocalPageWriter, type LocalPageInput, type NAP, defaultLocalTemplate } from "./localPageWriter.ts";

export function registerGroup04(): Record<string, AgentBase> {
    const all: Record<string, AgentBase> = {
        content_planner: new ContentPlanner(),
        blog_writer: new BlogWriter(),
        howto_writer: new HowtoWriter(),
        listicle_writer: new ListicleWriter(),
        comparison_writer: new ComparisonWriter(),
        local_page_writer: new LocalPageWriter(),
        faq_article_writer: new FaqArticleWriter(),
        case_study_writer: new CaseStudyWriter(),
        press_release_writer: new PressReleaseWriter(),
        email_writer: new EmailWriter(),
        video_script_writer: new VideoScriptWriter(),
    };
    for (const a of Object.values(all)) registerAgent(a);
    return all;
}
