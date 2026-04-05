"use client";

interface Props {
  status: string;
  progressPct?: number;
  progressStage?: string | null;
  progressDetail?: string | null;
  etaSeconds?: number | null;
}

const STEPS = [
  { key: "pending", label: "Queued", icon: "⏳" },
  { key: "transcribing", label: "Transcribing video", icon: "🎤" },
  { key: "detecting", label: "Detecting viral moments", icon: "🔍" },
  { key: "processing", label: "Processing clips", icon: "🎬" },
];

function formatEta(seconds: number): string {
  if (seconds < 60) return `~${seconds}s remaining`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `~${m}m ${s}s remaining`;
}

export default function ProcessingStatus({
  status,
  progressPct = 0,
  progressStage,
  progressDetail,
  etaSeconds,
}: Props) {
  const currentIndex = STEPS.findIndex((s) => s.key === status);

  return (
    <div className="card mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-medium">Processing Pipeline</h3>
        <span className="text-sm font-mono text-[#6d5dfc]">{progressPct}%</span>
      </div>

      {/* Progress Bar */}
      <div className="w-full h-2 bg-[#1a1a1a] rounded-full mb-1 overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-[#6d5dfc] to-[#a78bfa] rounded-full transition-all duration-700"
          style={{ width: `${Math.max(progressPct, 2)}%` }}
        />
      </div>

      {/* Stage detail + ETA */}
      <div className="flex items-center justify-between mb-4 text-xs text-[#888]">
        <span>{progressStage || ""}{progressDetail ? ` — ${progressDetail}` : ""}</span>
        {etaSeconds != null && etaSeconds > 0 && (
          <span>{formatEta(etaSeconds)}</span>
        )}
      </div>

      <div className="space-y-3">
        {STEPS.map((step, i) => {
          let state: "done" | "active" | "waiting" = "waiting";
          if (i < currentIndex) state = "done";
          else if (i === currentIndex) state = "active";

          return (
            <div
              key={step.key}
              className={`flex items-center gap-3 rounded-lg px-4 py-2.5 ${
                state === "active"
                  ? "bg-[#6d5dfc]/10 border border-[#6d5dfc]/30"
                  : state === "done"
                  ? "bg-green-500/5"
                  : "opacity-40"
              }`}
            >
              <span className="text-lg">
                {state === "done" ? "✅" : step.icon}
              </span>
              <span
                className={`text-sm ${
                  state === "active" ? "text-[#6d5dfc] font-medium" : ""
                }`}
              >
                {step.label}
              </span>
              {state === "active" && (
                <span className="ml-auto animate-spin h-4 w-4 border-2 border-[#6d5dfc] border-t-transparent rounded-full" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
