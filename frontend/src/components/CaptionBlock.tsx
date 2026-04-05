"use client";

import { useState } from "react";

interface Props {
  platform: string;
  icon: string;
  content: string | null;
}

export default function CaptionBlock({ platform, icon, content }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!content) return;
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!content) return null;

  return (
    <div className="rounded-lg border border-[#262626] bg-[#0a0a0a] p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium">
          {icon} {platform}
        </span>
        <button
          onClick={handleCopy}
          className="text-xs text-[#6d5dfc] hover:text-[#8b7dff] transition-colors"
        >
          {copied ? "✓ Copied!" : "📋 Copy"}
        </button>
      </div>
      <p className="whitespace-pre-wrap text-xs text-[#888] leading-relaxed max-h-40 overflow-y-auto">
        {content}
      </p>
    </div>
  );
}
