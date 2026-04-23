"use client";

import { useAuth } from "@/lib/auth";
import { useRouter, useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { getProject, Project } from "@/lib/api";
import Navbar from "@/components/Navbar";
import ClipCard from "@/components/ClipCard";
import ClipSelector from "@/components/ClipSelector";
import ProcessingStatus from "@/components/ProcessingStatus";

export default function ProjectPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const projectId = params.id as string;

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!authLoading && !user) router.push("/");
  }, [user, authLoading, router]);

  const fetchProject = useCallback(async () => {
    try {
      const data = await getProject(projectId);
      setProject(data);
    } catch (err: any) {
      setError(err.message || "Failed to load project");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (user) fetchProject();
  }, [user, fetchProject]);

  // Poll while processing (but not while waiting for the user to pick clips).
  useEffect(() => {
    if (!project) return;
    if (["done", "failed", "pending_selection"].includes(project.status)) return;
    const timer = setInterval(fetchProject, 4000);
    return () => clearInterval(timer);
  }, [project, fetchProject]);

  if (authLoading || loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-[#6d5dfc] border-t-transparent rounded-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen">
        <Navbar />
        <main className="mx-auto max-w-5xl px-4 py-8">
          <p className="text-red-500">{error}</p>
          <button onClick={() => router.push("/dashboard")} className="btn-secondary mt-4">
            ← Back to Dashboard
          </button>
        </main>
      </div>
    );
  }

  if (!project) return null;

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">
        {/* Header */}
        <div className="mb-6 flex items-center gap-4">
          <button
            onClick={() => router.push("/dashboard")}
            className="btn-secondary"
          >
            ← Back
          </button>
          <div>
            <h1 className="text-xl font-semibold">{project.title}</h1>
            <div className="flex items-center gap-3 mt-1">
              <StatusBadge status={project.status} />
              {project.duration && (
                <span className="text-sm text-[#888]">
                  {Math.round(project.duration)}s duration
                </span>
              )}
              {project.language && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-[#6d5dfc]/10 text-[#6d5dfc]">
                  {project.language}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Manual clip selection */}
        {project.status === "pending_selection" && project.source_filename && (
          <ClipSelector
            projectId={project.id}
            sourceFilename={project.source_filename}
            onSubmitted={fetchProject}
          />
        )}

        {/* Processing State */}
        {!(["done", "failed", "pending_selection"].includes(project.status)) && (
          <ProcessingStatus
            status={project.status}
            progressPct={project.progress_pct}
            progressStage={project.progress_stage}
            progressDetail={project.progress_detail}
            etaSeconds={project.eta_seconds}
          />
        )}

        {project.status === "failed" && (
          <div className="card border-red-500/30 mb-6">
            <p className="text-red-400">
              Processing failed. Check that FFmpeg, whisper.cpp, and Ollama are
              running correctly.
            </p>
          </div>
        )}

        {/* Clips */}
        {project.status === "done" && (
          <div>
            <h2 className="mb-4 text-lg font-semibold">
              {project.clips.length} Clip{project.clips.length !== 1 ? "s" : ""}{" "}
              Detected
            </h2>
            {project.clips.length === 0 ? (
              <p className="text-[#888]">No clips were detected in this video.</p>
            ) : (
              <div className="space-y-6">
                {project.clips
                  .sort((a, b) => b.score - a.score)
                  .map((clip, i) => (
                    <ClipCard key={clip.id} clip={clip} index={i + 1} />
                  ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: "badge-pending",
    pending_selection: "badge-pending",
    transcribing: "badge-processing",
    detecting: "badge-processing",
    processing: "badge-processing",
    done: "badge-done",
    failed: "badge-failed",
  };
  return <span className={`badge ${map[status] || "badge-pending"}`}>{status.replace("_", " ")}</span>;
}
