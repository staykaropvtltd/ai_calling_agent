import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign in — StayKaro",
};

// The login page is a pure routing page: it shows two entry paths
// (client/hotel login → /client/ and platform admin → /admin/).
// Actual credential handling lives in the respective dashboard apps.
// This page has no auth state of its own — it is a public directory page.

export default function LoginPage() {
  return (
    <div className="flex min-h-screen bg-fog">

      {/* Left panel — branding (desktop) */}
      <div className="hidden w-2/5 flex-col justify-between bg-graphite p-16 lg:flex">
        <Link
          href="/"
          className="font-display text-base font-normal tracking-display text-white/70 transition-colors hover:text-white"
        >
          ← StayKaro
        </Link>

        <div>
          <h1 className="mb-6 font-display text-heading font-normal leading-tight tracking-display text-white">
            AI Calling for Hospitality
          </h1>
          <p className="font-body text-sm leading-relaxed text-white/50">
            Automate guest communication, reservation confirmations, and
            follow-ups with an AI voice agent built for hotels and hospitality
            teams worldwide.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-white/10" />
          <span className="font-body text-xs text-white/30">staykaro.com</span>
        </div>
      </div>

      {/* Right panel — entry selection */}
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-16">

        {/* Mobile logo */}
        <div className="mb-10 lg:hidden">
          <Link
            href="/"
            className="font-display text-lg font-normal tracking-display text-graphite"
          >
            StayKaro
          </Link>
        </div>

        <div className="w-full max-w-sm">
          <h2 className="mb-1 font-display text-2xl font-normal tracking-display text-graphite">
            Sign in
          </h2>
          <p className="mb-8 font-body text-sm text-slate">
            Choose how you are accessing StayKaro.
          </p>

          <div className="flex flex-col gap-3">

            {/* Hotel / Client login → client dashboard */}
            <EntryCard
              href={process.env.NEXT_PUBLIC_CLIENT_URL ?? "/client"}
              iconBg="bg-ember"
              iconText="H"
              title="Hotel / Business"
              subtitle="Manage AI calling, customers, campaigns, and your team"
            />

            {/* Platform admin → admin dashboard */}
            <EntryCard
              href={process.env.NEXT_PUBLIC_ADMIN_URL ?? "/admin"}
              iconBg="bg-graphite"
              iconText="A"
              title="Platform Admin"
              subtitle="Manage all clients, users, system configuration and billing"
            />
          </div>

          <p className="mt-8 text-center font-body text-xs text-slate/60">
            Your role and access level are determined server-side.
            <br />
            The selection above is a routing choice, not an authorization bypass.
          </p>
        </div>
      </div>
    </div>
  );
}

function EntryCard({
  href,
  iconBg,
  iconText,
  title,
  subtitle,
}: {
  href: string;
  iconBg: string;
  iconText: string;
  title: string;
  subtitle: string;
}) {
  return (
    <a
      href={href}
      className="group flex items-center gap-4 border border-mist bg-canvas px-5 py-4 transition-colors hover:border-steel hover:bg-ash"
    >
      <div
        className={`flex h-10 w-10 flex-none items-center justify-center rounded-full ${iconBg}`}
      >
        <span className="font-display text-xs font-normal text-white">{iconText}</span>
      </div>
      <div className="flex-1">
        <div className="font-display text-sm font-normal tracking-display text-graphite">
          {title}
        </div>
        <div className="mt-0.5 font-body text-xs text-slate">{subtitle}</div>
      </div>
      <span className="text-mist transition-colors group-hover:text-slate">→</span>
    </a>
  );
}
