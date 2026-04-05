/**
 * API client for ClipFlow backend.
 * All calls go through Next.js rewrite → FastAPI.
 */

const BASE = "/api";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  // Don't set Content-Type for FormData (browser sets it with boundary)
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Auth ──
export function register(email: string, password: string) {
  return request<{ id: string; email: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function login(email: string, password: string) {
  return request<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function getMe() {
  return request<{
    id: string;
    email: string;
    plan: string;
    credits: number;
  }>("/auth/me");
}

// ── Projects ──
export interface ClipVersion {
  id: string;
  version_num: number;
  video_path: string | null;
  caption_instagram: string | null;
  caption_linkedin: string | null;
  caption_twitter: string | null;
  caption_youtube: string | null;
  custom_prompt: string | null;
  created_at: string;
}

export interface Project {
  id: string;
  title: string;
  video_url: string | null;
  duration: number | null;
  status: string;
  progress_pct: number;
  progress_stage: string | null;
  progress_detail: string | null;
  eta_seconds: number | null;
  language: string | null;
  created_at: string;
  clips: Clip[];
}

export interface Clip {
  id: string;
  clip_index: number;
  start_time: number;
  end_time: number;
  score: number;
  title: string | null;
  transcript_text: string | null;
  video_path: string | null;
  caption_instagram: string | null;
  caption_linkedin: string | null;
  caption_twitter: string | null;
  caption_youtube: string | null;
  active_version: number;
  versions: ClipVersion[];
  created_at: string;
}

export function uploadVideo(file?: File, videoUrl?: string) {
  const form = new FormData();
  if (file) form.append("file", file);
  if (videoUrl) form.append("video_url", videoUrl);

  return request<Project>("/projects/upload", {
    method: "POST",
    body: form,
  });
}

export function getProjects() {
  return request<Project[]>("/projects");
}

export function getProject(id: string) {
  return request<Project>(`/projects/${id}`);
}

export function deleteProject(id: string) {
  return request<void>(`/projects/${id}`, { method: "DELETE" });
}

// ── Clips ──
export function getClips(projectId: string) {
  return request<Clip[]>(`/clips/${projectId}`);
}

export function regenerateCaptions(clipId: string) {
  return request<Clip>(`/clips/${clipId}/regenerate`, { method: "POST" });
}

export async function downloadClip(clipId: string, title: string, version?: number) {
  const token = getToken();
  const vParam = version ? `?version=${version}` : "";
  const res = await fetch(`${BASE}/clips/${clipId}/download${vParam}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const vSuffix = version ? `_v${version}` : "";
  a.download = `${title}${vSuffix}.mp4`;
  a.click();
  URL.revokeObjectURL(url);
}

export function customizeClip(clipId: string, customPrompt: string) {
  return request<Clip>(`/clips/${clipId}/customize`, {
    method: "POST",
    body: JSON.stringify({ custom_prompt: customPrompt }),
  });
}

export function switchClipVersion(clipId: string, version: number) {
  return request<Clip>(`/clips/${clipId}/switch-version?version=${version}`, {
    method: "POST",
  });
}
