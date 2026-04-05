"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function Home() {
  const { user, loading, login, register } = useAuth();
  const router = useRouter();
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user) router.push("/dashboard");
  }, [user, loading, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (isLogin) {
        await login(email, password);
      } else {
        await register(email, password);
      }
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-[#6d5dfc] border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold">
            Clip<span className="text-[#6d5dfc]">Flow</span>
          </h1>
          <p className="mt-2 text-[#888]">
            Turn 1 long video into viral clips + captions
          </p>
        </div>

        {/* Auth Form */}
        <div className="card">
          <div className="mb-6 flex gap-2">
            <button
              onClick={() => setIsLogin(true)}
              className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                isLogin
                  ? "bg-[#6d5dfc] text-white"
                  : "bg-[#0a0a0a] text-[#888]"
              }`}
            >
              Sign In
            </button>
            <button
              onClick={() => setIsLogin(false)}
              className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                !isLogin
                  ? "bg-[#6d5dfc] text-white"
                  : "bg-[#0a0a0a] text-[#888]"
              }`}
            >
              Sign Up
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="input"
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="input"
            />
            {error && (
              <p className="text-sm text-red-500">{error}</p>
            )}
            <button
              type="submit"
              disabled={submitting}
              className="btn-primary w-full"
            >
              {submitting
                ? "Loading..."
                : isLogin
                ? "Sign In"
                : "Create Account"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
