// 049 — Video Script Writer.
// Full script + B-roll notes + CTA across short/medium/long lengths, plus
// YouTube SEO metadata and VideoObject schema.

import { AgentBase } from "../../core/AgentBase.ts";
import type { AgentInput, AgentOutput } from "../../core/types.ts";

export type VideoLength = "short" | "medium" | "long";

export interface ScriptSegment {
    timestamp: string;
    section: string;
    voiceover: string;
    b_roll: string;
}

export interface YouTubeMetadata {
    title: string;
    description: string;
    tags: string[];
    chapters: { time: string; label: string }[];
    pinned_comment: string;
}

export interface VideoObjectSchema {
    "@context": "https://schema.org";
    "@type": "VideoObject";
    name: string;
    description: string;
    duration: string;       // ISO-8601
    uploadDate: string;
    contentUrl?: string;
}

export type LlmFn = (prompt: string) => Promise<string>;

const LENGTH_CONFIG: Record<VideoLength, { totalSec: number; segments: number; iso: string }> = {
    short: { totalSec: 60, segments: 4, iso: "PT1M" },
    medium: { totalSec: 360, segments: 8, iso: "PT6M" },
    long: { totalSec: 1080, segments: 14, iso: "PT18M" },
};

function timecode(sec: number): string {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function buildSegments(topic: string, length: VideoLength): ScriptSegment[] {
    const cfg = LENGTH_CONFIG[length];
    const step = Math.floor(cfg.totalSec / cfg.segments);
    const segments: ScriptSegment[] = [];
    for (let i = 0; i < cfg.segments; i++) {
        const start = i * step;
        const isHook = i === 0;
        const isCta = i === cfg.segments - 1;
        const section = isHook ? "Hook" : isCta ? "CTA" : `Point ${i}`;
        const voiceover = isHook
            ? `Today we're covering ${topic} — stick around for the part most guides skip.`
            : isCta
                ? `If this helped, subscribe and check the description for the full ${topic} guide.`
                : `Here's point ${i} about ${topic}: a specific, actionable takeaway you can apply today.`;
        const broll = isHook
            ? `Wide establishing shot of ${topic} setting; overlay topic graphic.`
            : isCta
                ? `Subscribe-button animation; lower-third with channel handle.`
                : `Close-up demo footage relevant to ${topic}; on-screen text caption.`;
        segments.push({ timestamp: timecode(start), section, voiceover, b_roll: broll });
    }
    return segments;
}

function buildYouTubeMeta(topic: string, segments: ScriptSegment[]): YouTubeMetadata {
    const title = `${topic}: The Complete Guide`;
    const description = [
        `Everything you need to know about ${topic} in one video.`,
        ``,
        `Chapters:`,
        ...segments.map(s => `${s.timestamp} — ${s.section}`),
        ``,
        `Subscribe for more deep-dives on ${topic} and related topics.`,
    ].join("\n");
    const tags = [
        topic,
        `${topic} guide`,
        `${topic} tutorial`,
        `how to ${topic}`,
        `${topic} explained`,
        `${topic} tips`,
        `${topic} for beginners`,
    ];
    const chapters = segments.map(s => ({ time: s.timestamp, label: s.section }));
    const pinned_comment = `What part of ${topic} should we cover next? Drop a comment below.`;
    return { title, description, tags, chapters, pinned_comment };
}

export class VideoScriptWriter extends AgentBase {
    readonly id = "video_script_writer";
    readonly name = "Video Script Writer";
    readonly group = 4;
    readonly version = "1.0.0";

    async run(input: AgentInput): Promise<AgentOutput> {
        const topic = (input.topic as string | undefined) ?? (input.keyword as string | undefined);
        if (!topic) return { ok: false, error: "topic required" };
        const length = ((input.length as VideoLength | undefined) ?? "medium");
        if (!["short", "medium", "long"].includes(length)) {
            return { ok: false, error: "length must be short|medium|long" };
        }
        const llmFn = input.llm_fn as LlmFn | undefined;

        let segments = buildSegments(topic, length);
        if (llmFn) {
            // Per-segment LLM rewrite of voiceover only; structure stays deterministic.
            const rewritten: ScriptSegment[] = [];
            for (const seg of segments) {
                const raw = await llmFn(`Rewrite this voiceover for ${topic} (${seg.section}): ${seg.voiceover}`);
                rewritten.push({ ...seg, voiceover: raw.trim() || seg.voiceover });
            }
            segments = rewritten;
        }

        const cfg = LENGTH_CONFIG[length];
        const yt = buildYouTubeMeta(topic, segments);
        const schema: VideoObjectSchema = {
            "@context": "https://schema.org",
            "@type": "VideoObject",
            name: yt.title,
            description: yt.description.slice(0, 5000),
            duration: cfg.iso,
            uploadDate: new Date().toISOString(),
        };

        const fullScript = segments
            .map(s => `[${s.timestamp}] ${s.section}\nVO: ${s.voiceover}\nB-ROLL: ${s.b_roll}`)
            .join("\n\n");

        return {
            ok: true,
            data: {
                topic,
                length,
                duration_sec: cfg.totalSec,
                segments,
                full_script: fullScript,
                youtube: yt,
                schema,
            },
        };
    }
}
