"use client";

import { useState, useRef } from "react";

interface Props {
  onUpload: (file?: File, url?: string) => Promise<void>;
}

export default function UploadForm({ onUpload }: Props) {
  const [mode, setMode] = useState<"file" | "url">("file");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setUploading(true);
    try {
      if (mode === "file" && file) {
        await onUpload(file, undefined);
      } else if (mode === "url" && url) {
        await onUpload(undefined, url);
      }
      setFile(null);
      setUrl("");
      if (inputRef.current) inputRef.current.value = "";
    } catch (err: any) {
      setError(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="card">
      <h2 className="mb-4 text-lg font-semibold">Upload Video</h2>

      {/* Mode Toggle */}
      <div className="mb-4 flex gap-2">
        <button
          type="button"
          onClick={() => setMode("file")}
          className={`rounded-lg px-4 py-1.5 text-sm transition-colors ${
            mode === "file"
              ? "bg-[#6d5dfc]/20 text-[#6d5dfc]"
              : "text-[#888] hover:text-[#ededed]"
          }`}
        >
          📁 File Upload
        </button>
        <button
          type="button"
          onClick={() => setMode("url")}
          className={`rounded-lg px-4 py-1.5 text-sm transition-colors ${
            mode === "url"
              ? "bg-[#6d5dfc]/20 text-[#6d5dfc]"
              : "text-[#888] hover:text-[#ededed]"
          }`}
        >
          🔗 YouTube URL
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {mode === "file" ? (
          <div>
            <input
              ref={inputRef}
              type="file"
              accept="video/*"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="input file:mr-4 file:rounded-lg file:border-0 file:bg-[#6d5dfc]/20 file:px-4 file:py-1 file:text-sm file:text-[#6d5dfc] cursor-pointer"
            />
            {file && (
              <p className="mt-2 text-sm text-[#888]">
                {file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)
              </p>
            )}
          </div>
        ) : (
          <input
            type="url"
            placeholder="https://www.youtube.com/watch?v=..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="input"
          />
        )}

        {error && <p className="text-sm text-red-500">{error}</p>}

        <button
          type="submit"
          disabled={uploading || (mode === "file" ? !file : !url)}
          className="btn-primary"
        >
          {uploading ? (
            <span className="flex items-center gap-2">
              <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
              Processing...
            </span>
          ) : (
            "🚀 Start Processing"
          )}
        </button>
      </form>
    </div>
  );
}
