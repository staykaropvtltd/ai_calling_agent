"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../lib/auth/useAuth";
import { ErrorBanner } from "../../components/ErrorBanner";

export default function LoginPage() {
  const { login, status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login({ email, password });
      router.push("/");
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "authenticated") {
    router.replace("/");
    return null;
  }

  return (
    <div className="flex min-h-screen">
      {/* Dark left panel */}
      <div className="hidden w-[420px] shrink-0 flex-col justify-between bg-graphite p-12 lg:flex">
        <div>
          <div className="mb-12 flex h-10 w-10 items-center justify-center rounded-full bg-ember">
            <span className="font-display text-sm font-bold text-white">SK</span>
          </div>
          <h1 className="font-display text-3xl font-semibold leading-tight text-white">
            StayKaro
            <br />
            Platform
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-white/50">
            Manage hotel clients, users, call infrastructure, and platform analytics from a single
            control plane.
          </p>
        </div>
        <p className="text-xs text-white/30">Platform Admin · Super-admin access only</p>
      </div>

      {/* Right form panel */}
      <div className="flex flex-1 flex-col items-center justify-center bg-fog px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-full bg-ember">
              <span className="font-display text-xs font-bold text-white">SK</span>
            </div>
            <h1 className="font-display text-xl font-semibold text-graphite">StayKaro Platform</h1>
          </div>

          <h2 className="mb-1 font-display text-xl font-semibold text-graphite">Sign in</h2>
          <p className="mb-8 text-sm text-slate-neutral">Platform administrator access only.</p>

          {error ? (
            <div className="mb-5">
              <ErrorBanner error={error} />
            </div>
          ) : null}

          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="email" className="text-xs font-medium uppercase tracking-widest text-steel">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-graphite focus:outline-none"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="password" className="text-xs font-medium uppercase tracking-widest text-steel">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-graphite focus:outline-none"
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="mt-2 bg-graphite px-5 py-3 font-display text-sm font-medium text-white transition-colors hover:bg-steel disabled:opacity-50"
            >
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
