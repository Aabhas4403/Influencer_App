"use client";

import { useEffect, useRef, useState } from "react";
import { submitSelections } from "@/lib/api";

interface Range {
  start: number;
  end: number;
}

interface Props {
  projectId: string;
  sourceFilename: string;
  onSubmitted: () => void;
}

const fmt = (s: number) => {
  if (!Number.isFinite(s)) return "0:00.0";
  const m = Math.floor(s / 60);
  const sec = (s - m * 60).toFixed(1);
  return `${m}:${sec.padStart(4, "0")}`;
};

export default function ClipSelector({ projectId, sourceFilename, onSubmitted }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [markStart, setMarkStart] = useState<number | null>(null);
  const [ranges, setRanges] = useState<Range[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Keep currentTime fresh while playing/scrubbing.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setCurrentTime(v.currentTime);
    const onMeta = () => setDuration(v.duration || 0);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onMeta);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onMeta);
    };
  }, []);

  const seek = (t: number) => {
    const v = videoRef.current;
    if (!v) return;
    const target = Math.max(0, Math.min(duration || t, t));
    v.currentTime = target;
    setCurrentTime(target);
  };

  const seekAndPlay = (t: number) => {
    const v = videoRef.current;
    if (!v) return;
    seek(t);
    v.play().catch(() => { /* autoplay may be blocked, ignore */ });
  };

  // Click + drag scrubbing on the timeline strip.
  const timelineRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const seekFromClientX = (clientX: number) => {
    const el = timelineRef.current;
    if (!el || duration <= 0) return;
    const rect = el.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    seek(ratio * duration);
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (draggingRef.current) seekFromClientX(e.clientX);
    };
    const onUp = () => { draggingRef.current = false; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duration]);

  const handleMark = () => {
    if (markStart === null) {
      setMarkStart(currentTime);
    } else {
      const s = Math.min(markStart, currentTime);
      const e = Math.max(markStart, currentTime);
      if (e - s < 2) {
        setError("Selection too short — minimum 2 seconds.");
        return;
      }
      setRanges((prev) => [...prev, { start: s, end: e }].sort((a, b) => a.start - b.start));
      setMarkStart(null);
      setError("");
    }
  };

  const removeRange = (i: number) => {
    setRanges((prev) => prev.filter((_, idx) => idx !== i));
  };

  const updateRange = (i: number, key: "start" | "end", value: number) => {
    setRanges((prev) =>
      prev.map((r, idx) => {
        if (idx !== i) return r;
        const next = { ...r, [key]: value };
        return next;
      })
    );
  };

  const handleSubmit = async () => {
    if (ranges.length === 0) {
      setError("Add at least one clip range.");
      return;
    }
    for (const r of ranges) {
      if (r.end <= r.start) {
        setError("Each range must have end > start.");
        return;
      }
      if (r.end - r.start < 2) {
        setError("Each clip must be at least 2 seconds.");
        return;
      }
    }
    setSubmitting(true);
    setError("");
    try {
      await submitSelections(projectId, ranges);
      onSubmitted();
    } catch (err: any) {
      setError(err.message || "Failed to submit selections.");
    } finally {
      setSubmitting(false);
    }
  };

  const startPct = markStart !== null && duration ? (Math.min(markStart, currentTime) / duration) * 100 : 0;
  const endPct = markStart !== null && duration ? (Math.max(markStart, currentTime) / duration) * 100 : 0;

  return (
    <div className="card">
      <h2 className="mb-2 text-lg font-semibold">Pick your clips</h2>
      <p className="mb-4 text-sm text-[#888]">
        Drag the slider or timeline to jump anywhere in the video, then tap{" "}
        <span className="text-[#ededed]">Mark in</span> at the start of a moment and{" "}
        <span className="text-[#ededed]">Mark out</span> at the end. Repeat for as many clips as you like.
      </p>

      {/* Video player */}
      <div className="mb-4 overflow-hidden rounded-lg bg-black">
        <video
          ref={videoRef}
          src={`/uploads/${sourceFilename}`}
          controls
          playsInline
          className="w-full max-h-[420px]"
        />
      </div>

      {/* Scrub slider — instant, no need to watch the video */}
      {duration > 0 && (
        <div className="mb-3">
          <input
            type="range"
            min={0}
            max={duration}
            step={0.1}
            value={currentTime}
            onChange={(e) => seek(parseFloat(e.target.value))}
            className="w-full accent-[#6d5dfc] cursor-pointer"
          />
        </div>
      )}

      {/* Timeline with committed ranges + in-progress range overlay (click/drag to scrub) */}
      <div
        ref={timelineRef}
        onMouseDown={(e) => {
          draggingRef.current = true;
          seekFromClientX(e.clientX);
        }}
        className="relative mb-3 h-4 w-full cursor-pointer rounded-full bg-[#1f1f1f] hover:h-5 transition-all"
      >
        {/* All committed ranges */}
        {duration > 0 &&
          ranges.map((r, i) => (
            <div
              key={i}
              className="absolute top-0 h-full rounded-full bg-[#6d5dfc]/60"
              style={{
                left: `${(r.start / duration) * 100}%`,
                width: `${((r.end - r.start) / duration) * 100}%`,
              }}
              title={`${fmt(r.start)} → ${fmt(r.end)}`}
            />
          ))}
        {/* In-progress range (after Mark in, before Mark out) */}
        {markStart !== null && duration > 0 && (
          <div
            className="absolute top-0 h-full rounded-full bg-yellow-400/50"
            style={{ left: `${startPct}%`, width: `${Math.max(endPct - startPct, 0.5)}%` }}
          />
        )}
        {/* Playhead */}
        {duration > 0 && (
          <div
            className="pointer-events-none absolute top-[-4px] h-[24px] w-[3px] rounded-full bg-[#ededed] shadow"
            style={{ left: `${(currentTime / duration) * 100}%` }}
          />
        )}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-[#888]">{fmt(currentTime)} / {fmt(duration)}</span>
        <button type="button" onClick={() => seek(currentTime - 5)} className="btn-secondary !px-3 !py-1">
          ⟲ 5s
        </button>
        <button type="button" onClick={() => seek(currentTime + 5)} className="btn-secondary !px-3 !py-1">
          5s ⟳
        </button>
        <button
          type="button"
          onClick={handleMark}
          className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
            markStart === null
              ? "bg-[#6d5dfc]/20 text-[#6d5dfc] hover:bg-[#6d5dfc]/30"
              : "bg-yellow-400/20 text-yellow-300 hover:bg-yellow-400/30"
          }`}
        >
          {markStart === null ? "🟣 Mark in" : `🟡 Mark out (in @ ${fmt(markStart)})`}
        </button>
        {markStart !== null && (
          <button type="button" onClick={() => setMarkStart(null)} className="text-xs text-[#888] hover:text-[#ededed]">
            cancel
          </button>
        )}
      </div>

      {/* Selected ranges list */}
      {ranges.length > 0 && (
        <div className="mb-4 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-[#ededed]">{ranges.length} clip(s) selected</p>
            <button
              type="button"
              onClick={() => {
                setRanges([]);
                setMarkStart(null);
                setError("");
              }}
              className="text-xs text-red-400 hover:text-red-300"
            >
              ↻ Clear all
            </button>
          </div>
          {ranges.map((r, i) => (
            <div key={i} className="flex items-center gap-2 rounded-lg bg-[#161616] px-3 py-2 text-sm">
              <span className="font-mono text-[#6d5dfc]">#{i + 1}</span>
              <input
                type="number"
                step="0.1"
                value={r.start.toFixed(1)}
                onChange={(e) => updateRange(i, "start", parseFloat(e.target.value) || 0)}
                className="w-20 rounded bg-[#0d0d0d] px-2 py-1 text-xs"
              />
              <span className="text-[#555]">→</span>
              <input
                type="number"
                step="0.1"
                value={r.end.toFixed(1)}
                onChange={(e) => updateRange(i, "end", parseFloat(e.target.value) || 0)}
                className="w-20 rounded bg-[#0d0d0d] px-2 py-1 text-xs"
              />
              <span className="text-xs text-[#888]">{(r.end - r.start).toFixed(1)}s</span>
              <button type="button" onClick={() => seekAndPlay(r.start)} className="ml-auto text-xs text-[#888] hover:text-[#ededed]">
                ▶ preview
              </button>
              <button type="button" onClick={() => removeRange(i)} className="text-xs text-red-400 hover:text-red-300">
                remove
              </button>
            </div>
          ))}
        </div>
      )}

      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={submitting || ranges.length === 0}
        className="btn-primary"
      >
        {submitting ? "Submitting..." : `🚀 Process ${ranges.length || ""} clip${ranges.length === 1 ? "" : "s"}`}
      </button>
    </div>
  );
}
