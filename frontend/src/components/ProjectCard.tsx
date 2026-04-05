"use client";

import { Project } from "@/lib/api";

interface Props {
  project: Project;
  onDelete: (id: string) => void;
  onClick: () => void;
}

export default function ProjectCard({ project, onDelete, onClick }: Props) {
  const statusMap: Record<string, string> = {
    pending: "badge-pending",
    transcribing: "badge-processing",
    detecting: "badge-processing",
    processing: "badge-processing",
    done: "badge-done",
    failed: "badge-failed",
  };

  return (
    <div
      onClick={onClick}
      className="card flex cursor-pointer items-center justify-between transition-colors hover:border-[#6d5dfc]/40"
    >
      <div className="flex-1">
        <div className="flex items-center gap-3">
          <h3 className="font-medium">{project.title}</h3>
          <span className={`badge ${statusMap[project.status] || "badge-pending"}`}>
            {project.status}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-4 text-sm text-[#888]">
          {project.duration && (
            <span>{Math.round(project.duration)}s</span>
          )}
          <span>{project.clips.length} clips</span>
          <span>{new Date(project.created_at).toLocaleDateString()}</span>
          {project.language && <span>🌐 {project.language}</span>}
        </div>
        {/* Mini progress bar for in-progress projects */}
        {!["done", "failed"].includes(project.status) && project.progress_pct > 0 && (
          <div className="mt-2">
            <div className="w-full h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#6d5dfc] rounded-full transition-all duration-500"
                style={{ width: `${project.progress_pct}%` }}
              />
            </div>
            <div className="mt-0.5 text-xs text-[#666]">
              {project.progress_pct}% — {project.progress_stage}
            </div>
          </div>
        )}
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete(project.id);
        }}
        className="text-[#888] hover:text-red-400 transition-colors text-sm"
      >
        Delete
      </button>
    </div>
  );
}
