"use client";

import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";

export default function Navbar() {
  const { user, logout } = useAuth();
  const router = useRouter();

  return (
    <nav className="sticky top-0 z-50 border-b border-[#262626] bg-[#0a0a0a]/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <button
          onClick={() => router.push("/dashboard")}
          className="text-lg font-bold"
        >
          Clip<span className="text-[#6d5dfc]">Flow</span>
        </button>
        {user && (
          <div className="flex items-center gap-4">
            <span className="text-sm text-[#888]">{user.email}</span>
            <span className="badge badge-done">{user.plan}</span>
            <button onClick={logout} className="btn-secondary text-xs">
              Sign Out
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
