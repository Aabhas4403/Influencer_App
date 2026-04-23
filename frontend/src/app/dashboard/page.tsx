"use client";

import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { getProjects, uploadVideo, deleteProject, Project } from "@/lib/api";
import Navbar from "@/components/Navbar";
import UploadForm from "@/components/UploadForm";
import ProjectCard from "@/components/ProjectCard";

export default function Dashboard() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    if (!loading && !user) router.push("/");
  }, [user, loading, router]);

  const fetchProjects = useCallback(async () => {
    try {
      const data = await getProjects();
      setProjects(data);
    } catch {
      // ignore
    } finally {
      setFetching(false);
    }
  }, []);

  useEffect(() => {
    if (user) fetchProjects();
  }, [user, fetchProjects]);

  // Poll for status updates every 5s if any project is still processing
  useEffect(() => {
    const hasProcessing = projects.some(
      (p) => !["done", "failed"].includes(p.status)
    );
    if (!hasProcessing) return;

    const timer = setInterval(fetchProjects, 5000);
    return () => clearInterval(timer);
  }, [projects, fetchProjects]);

  const handleUpload = async (file?: File, url?: string, manualSelect?: boolean) => {
    const project = await uploadVideo(file, url, manualSelect);
    setProjects((prev) => [project, ...prev]);
    // If the user opted to pick clips manually, jump straight to the project page.
    if (manualSelect) {
      router.push(`/project/${project.id}`);
    }
  };

  const handleDelete = async (id: string) => {
    await deleteProject(id);
    setProjects((prev) => prev.filter((p) => p.id !== id));
  };

  if (loading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-[#6d5dfc] border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">
        {/* Upload Section */}
        <UploadForm onUpload={handleUpload} />

        {/* Projects List */}
        <div className="mt-10">
          <h2 className="mb-4 text-lg font-semibold">Your Projects</h2>
          {fetching ? (
            <div className="text-[#888]">Loading projects...</div>
          ) : projects.length === 0 ? (
            <div className="card text-center text-[#888]">
              <p>No projects yet. Upload a video to get started!</p>
            </div>
          ) : (
            <div className="space-y-4">
              {projects.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onDelete={handleDelete}
                  onClick={() => router.push(`/project/${project.id}`)}
                />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
