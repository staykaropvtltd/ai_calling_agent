"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../lib/auth/useAuth";
import { ErrorBanner } from "../../components/ErrorBanner";

type EntryMode = "pick" | "client" | "user";

export default function LoginPage() {
  const { login, status } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<EntryMode>("pick");
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
    <div className="flex min-h-screen bg-fog">
      {/* Left panel — branding */}
      <div className="hidden w-2/5 flex-col justify-between bg-graphite p-12 lg:flex">
        <div>
          <span className="font-display text-lg font-semibold tracking-display text-white">
            StayKaro
          </span>
        </div>
        <div>
          <p className="mb-6 max-w-xs font-display text-3xl font-semibold leading-snug tracking-display text-white">
            AI Calling &amp; Automation for Hospitality
          </p>
          <p className="text-sm leading-relaxed text-white/50">
            Automate guest communication, reservation confirmations, and
            follow-ups with an AI voice agent built for hotels.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-white/10" />
          <span className="text-xs text-white/30">staykaro.com</span>
        </div>
      </div>

      {/* Right panel — auth */}
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-12">
        {/* Mobile logo */}
        <div className="mb-8 lg:hidden">
          <span className="font-display text-xl font-semibold tracking-display text-graphite">
            StayKaro
          </span>
        </div>

        <div className="w-full max-w-sm">
          {mode === "pick" ? (
            <EntryPicker onSelect={setMode} />
          ) : (
            <LoginForm
              mode={mode}
              email={email}
              password={password}
              submitting={submitting}
              error={error}
              onEmailChange={setEmail}
              onPasswordChange={setPassword}
              onSubmit={handleSubmit}
              onBack={() => {
                setMode("pick");
                setError(null);
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function EntryPicker({ onSelect }: { onSelect: (m: EntryMode) => void }) {
  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-semibold tracking-display text-graphite">
        Sign in
      </h1>
      <p className="mb-8 text-sm text-slate-neutral">
        Choose how you&apos;re accessing StayKaro.
      </p>

      <div className="flex flex-col gap-3">
        {/* Admin tile → separate Next.js app */}
        <a
          href="/admin/"
          className="group flex items-center gap-4 rounded-2xl border border-mist bg-canvas px-5 py-4 transition-colors hover:border-steel hover:bg-ash"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-graphite">
            <span className="font-display text-xs font-bold text-white">SA</span>
          </div>
          <div className="flex-1">
            <div className="font-display text-sm font-semibold text-graphite">
              Platform Admin
            </div>
            <div className="text-xs text-slate-neutral">
              Manage all clients, users and system settings
            </div>
          </div>
          <span className="text-slate-neutral transition-colors group-hover:text-graphite">
            →
          </span>
        </a>

        {/* Client tile */}
        <button
          type="button"
          onClick={() => onSelect("client")}
          className="group flex items-center gap-4 rounded-2xl border border-mist bg-canvas px-5 py-4 text-left transition-colors hover:border-steel hover:bg-ash"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-ember">
            <span className="font-display text-xs font-bold text-white">CA</span>
          </div>
          <div className="flex-1">
            <div className="font-display text-sm font-semibold text-graphite">
              Client Administrator
            </div>
            <div className="text-xs text-slate-neutral">
              Manage your hotel&apos;s AI calling setup and team
            </div>
          </div>
          <span className="text-slate-neutral transition-colors group-hover:text-graphite">
            →
          </span>
        </button>

        {/* User tile */}
        <button
          type="button"
          onClick={() => onSelect("user")}
          className="group flex items-center gap-4 rounded-2xl border border-mist bg-canvas px-5 py-4 text-left transition-colors hover:border-steel hover:bg-ash"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full border border-mist bg-fog">
            <span className="font-display text-xs font-medium text-steel">U</span>
          </div>
          <div className="flex-1">
            <div className="font-display text-sm font-semibold text-graphite">
              User / Agent
            </div>
            <div className="text-xs text-slate-neutral">
              Place calls and view your team&apos;s activity
            </div>
          </div>
          <span className="text-slate-neutral transition-colors group-hover:text-graphite">
            →
          </span>
        </button>
      </div>

      <p className="mt-6 text-center text-xs text-slate-neutral/60">
        Your role and access level are determined by the platform.
      </p>
    </div>
  );
}

function LoginForm({
  mode,
  email,
  password,
  submitting,
  error,
  onEmailChange,
  onPasswordChange,
  onSubmit,
  onBack,
}: {
  mode: EntryMode;
  email: string;
  password: string;
  submitting: boolean;
  error: unknown;
  onEmailChange: (v: string) => void;
  onPasswordChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  onBack: () => void;
}) {
  const labels: Record<"client" | "user", { title: string; sub: string }> = {
    client: {
      title: "Client sign in",
      sub: "Sign in to your hotel's StayKaro account.",
    },
    user: {
      title: "Team member sign in",
      sub: "Access your calling dashboard and activity.",
    },
  };
  const { title, sub } = labels[mode as "client" | "user"];

  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        className="mb-6 flex items-center gap-1.5 text-xs text-slate-neutral transition-colors hover:text-graphite"
      >
        ← Back
      </button>

      <h1 className="mb-1 font-display text-2xl font-semibold tracking-display text-graphite">
        {title}
      </h1>
      <p className="mb-8 text-sm text-slate-neutral">{sub}</p>

      {error ? (
        <div className="mb-5">
          <ErrorBanner error={error} />
        </div>
      ) : null}

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="email"
            className="text-xs font-medium uppercase tracking-widest text-steel"
          >
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => onEmailChange(e.target.value)}
            className="rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite placeholder:text-slate-neutral focus:border-steel focus:outline-none focus:ring-1 focus:ring-graphite/20 transition-colors"
            placeholder="you@yourhotel.com"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="password"
            className="text-xs font-medium uppercase tracking-widest text-steel"
          >
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => onPasswordChange(e.target.value)}
            className="rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite placeholder:text-slate-neutral focus:border-steel focus:outline-none focus:ring-1 focus:ring-graphite/20 transition-colors"
            placeholder="••••••••"
          />
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="mt-2 bg-graphite px-5 py-2.5 font-display text-sm font-medium tracking-wide text-white transition-colors hover:bg-steel disabled:opacity-40"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
