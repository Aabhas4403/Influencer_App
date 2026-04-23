"use client";

import { useState } from "react";
import {
  Clip,
  regenerateCaptions,
  downloadClip,
  customizeClip,
  switchClipVersion,
} from "@/lib/api";
import CaptionBlock from "./CaptionBlock";

interface Props {
  clip: Clip;
  index: number;
}

export default function ClipCard({ clip, index }: Props) {
  const [data, setData] = useState(clip);
  const [regenerating, setRegenerating] = useState(false);
  const [customPrompt, setCustomPrompt] = useState("");
  const [customizing, setCustomizing] = useState(false);
  const [showCustomize, setShowCustomize] = useState(false);
  const [showWhy, setShowWhy] = useState(false);

  let features: Record<string, number> | null = null;
  if (data.score_features) {
    try {
      features = JSON.parse(data.score_features);
    } catch {
      features = null;
    }
  }

  let hookVariants: string[] = [];
  if (data.hook_variants) {
    try {
      const parsed = JSON.parse(data.hook_variants);
      if (Array.isArray(parsed)) hookVariants = parsed.filter((s) => typeof s === "string");
    } catch {
      hookVariants = [];
    }
  }

  const applyHook = async (hook: string) => {
    setCustomizing(true);
    try {
      // Reuse the customize flow — uses keyword "professional" so the video re-renders.
      await customizeClip(
        data.id,
        `Use this exact viral hook as the title and rewrite the opening line of the transcript to use it: "${hook}". Keep everything else professional.`
      );
    } catch {
      // silent fail
    } finally {
      setCustomizing(false);
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const updated = await regenerateCaptions(data.id);
      setData(updated);
    } catch {
      // silent fail
    } finally {
      setRegenerating(false);
    }
  };

  const handleCustomize = async () => {
    if (!customPrompt.trim()) return;
    setCustomizing(true);
    try {
      await customizeClip(data.id, customPrompt.trim());
      setCustomPrompt("");
      setShowCustomize(false);
      // The customization runs in background — poll will update
    } catch {
      // silent fail
    } finally {
      setCustomizing(false);
    }
  };

  const handleSwitchVersion = async (version: number) => {
    try {
      const updated = await switchClipVersion(data.id, version);
      setData(updated);
    } catch {
      // silent fail
    }
  };

  const duration = data.end_time - data.start_time;

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#6d5dfc] text-xs font-bold">
              {index}
            </span>
            <h3 className="font-medium">{data.title || `Clip ${index}`}</h3>
            {data.versions.length > 1 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-[#6d5dfc]/20 text-[#6d5dfc]">
                V{data.active_version}
              </span>
            )}
          </div>
          <div className="mt-1 flex items-center gap-3 text-sm text-[#888]">
            <span>⏱ {duration.toFixed(1)}s</span>
            <span>🔥 Score: {data.score.toFixed(1)}</span>
            <span>
              {formatTime(data.start_time)} → {formatTime(data.end_time)}
            </span>
            {features && (
              <button
                onClick={() => setShowWhy(!showWhy)}
                className="text-xs text-[#6d5dfc] hover:underline"
              >
                {showWhy ? "Hide" : "Why this clip?"}
              </button>
            )}
          </div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setShowCustomize(!showCustomize)}
            className="btn-secondary text-xs"
          >
            ✏️ Customize
          </button>
          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            className="btn-secondary text-xs"
          >
            {regenerating ? "..." : "🔄 Regenerate"}
          </button>
          {data.video_path && (
            <button
              onClick={() =>
                downloadClip(
                  data.id,
                  data.title || `clip_${index}`,
                  data.active_version
                )
              }
              className="btn-primary text-xs inline-flex items-center"
            >
              ⬇ Download
            </button>
          )}
        </div>
      </div>

      {/* Version Selector */}
      {data.versions.length > 1 && (
        <div className="mb-4 flex items-center gap-2 flex-wrap">
          <span className="text-xs text-[#888]">Versions:</span>
          {data.versions.map((v) => (
            <button
              key={v.id}
              onClick={() => handleSwitchVersion(v.version_num)}
              className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                v.version_num === data.active_version
                  ? "border-[#6d5dfc] bg-[#6d5dfc]/20 text-[#6d5dfc]"
                  : "border-[#333] text-[#888] hover:border-[#6d5dfc]/40"
              }`}
            >
              V{v.version_num}
              {v.custom_prompt && (
                <span className="ml-1 opacity-60" title={v.custom_prompt}>
                  ✏️
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Custom Requirements Panel */}
      {showCustomize && (
        <div className="mb-4 rounded-lg border border-[#333] p-4">
          <label className="text-xs font-medium text-[#ededed] mb-2 block">
            Custom Requirements
          </label>
          <textarea
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            placeholder="e.g. Make it more professional, add humor, focus on the key insight, use Hindi language..."
            className="w-full rounded-lg bg-[#0a0a0a] border border-[#333] p-3 text-sm text-[#ededed] placeholder-[#555] resize-none focus:border-[#6d5dfc] focus:outline-none"
            rows={3}
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              onClick={() => setShowCustomize(false)}
              className="btn-secondary text-xs"
            >
              Cancel
            </button>
            <button
              onClick={handleCustomize}
              disabled={customizing || !customPrompt.trim()}
              className="btn-primary text-xs"
            >
              {customizing ? "Processing..." : "🚀 Run Changes"}
            </button>
          </div>
        </div>
      )}

      {/* Why this clip? — multi-signal score breakdown */}
      {showWhy && features && (
        <div className="mb-4 rounded-lg border border-[#6d5dfc]/20 bg-[#6d5dfc]/5 p-3">
          <p className="mb-2 text-xs font-medium text-[#ededed]">
            Why this clip? — multi-signal virality score
          </p>
          <div className="space-y-1.5">
            {Object.entries(features).map(([k, v]) => {
              const pct = Math.max(0, Math.min(1, v)) * 100;
              return (
                <div key={k} className="flex items-center gap-2 text-xs">
                  <span className="w-20 shrink-0 capitalize text-[#888]">{k}</span>
                  <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-[#1f1f1f]">
                    <div
                      className="absolute left-0 top-0 h-full rounded-full bg-[#6d5dfc]"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right font-mono text-[#aaa]">
                    {(v as number).toFixed(2)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* A/B Hook Variants — pick a different viral hook for this clip */}
      {hookVariants.length > 0 && (
        <div className="mb-4 rounded-lg border border-[#333] bg-[#0a0a0a] p-3">
          <p className="mb-2 text-xs font-medium text-[#ededed]">
            🎯 Hook variants <span className="text-[#888]">— A/B test which hook performs best</span>
          </p>
          <div className="space-y-2">
            {hookVariants.map((hook, i) => (
              <div
                key={i}
                className="flex items-start gap-2 rounded-md border border-[#222] bg-[#0d0d0d] p-2"
              >
                <span className="mt-0.5 text-xs font-mono text-[#6d5dfc]">#{i + 1}</span>
                <p className="flex-1 text-sm text-[#ededed]">{hook}</p>
                <button
                  type="button"
                  onClick={() => navigator.clipboard?.writeText(hook)}
                  className="text-xs text-[#888] hover:text-[#ededed]"
                  title="Copy hook to clipboard"
                >
                  📋
                </button>
                <button
                  type="button"
                  onClick={() => applyHook(hook)}
                  disabled={customizing}
                  className="text-xs text-[#6d5dfc] hover:underline disabled:opacity-50"
                  title="Re-render this clip using this hook"
                >
                  {customizing ? "..." : "Use →"}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Transcript */}
      {data.transcript_text && (
        <div className="mb-4 rounded-lg bg-[#0a0a0a] p-3 text-sm text-[#888]">
          <span className="text-xs font-medium text-[#ededed]">Transcript: </span>
          {data.transcript_text}
        </div>
      )}

      {/* Captions Grid */}
      <div className="grid gap-3 sm:grid-cols-2">
        <CaptionBlock
          platform="Instagram"
          icon="📸"
          content={data.caption_instagram}
        />
        <CaptionBlock
          platform="LinkedIn"
          icon="💼"
          content={data.caption_linkedin}
        />
        <CaptionBlock
          platform="Twitter/X"
          icon="🐦"
          content={data.caption_twitter}
        />
        <CaptionBlock
          platform="YouTube"
          icon="🎬"
          content={data.caption_youtube}
        />
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
