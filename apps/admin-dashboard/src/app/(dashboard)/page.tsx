"use client";

import { useAuth } from "../../lib/auth/useAuth";
import { useTenantsQuery } from "../../lib/hooks/useTenants";
import { useCallsQuery } from "../../lib/hooks/useCalls";
import { useUsersQuery } from "../../lib/hooks/useUsers";
import { StatCard } from "../../components/Card";
import { Card } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
import { Spinner } from "../../components/Spinner";
import { AnchorButton } from "../../components/Button";

export default function OverviewPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";

  const tenants = useTenantsQuery({ page: 1, per_page: 1 });
  const users = useUsersQuery({ page: 1, per_page: 1 });
  const calls = useCallsQuery({ page: 1, per_page: 1 });

  return (
    <div>
      <PageHeader
        eyebrow="Platform"
        title={`Welcome, ${user?.full_name?.split(" ")[0] ?? "Admin"}`}
        description="StayKaro platform overview."
      />

      {/* Asymmetric stat grid */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {isSuperAdmin ? (
          <div className="sm:col-span-1">
            <StatCard
              label="Hotel clients"
              value={tenants.isLoading ? <Spinner size="sm" /> : tenants.isError ? "—" : tenants.data?.total ?? 0}
              accent
            />
          </div>
        ) : null}
        <StatCard
          label="Total users"
          value={users.isLoading ? <Spinner size="sm" /> : users.isError ? "—" : users.data?.total ?? 0}
        />
        <StatCard
          label="Total calls"
          value={calls.isLoading ? <Spinner size="sm" /> : calls.isError ? "—" : calls.data?.total ?? 0}
        />
      </div>

      {/* Featured links */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card tint="ivory" className="sm:col-span-2">
          <p className="mb-1 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            Quick actions
          </p>
          <p className="mb-4 font-display text-lg font-semibold text-graphite">
            Manage the platform
          </p>
          <div className="flex flex-wrap gap-3">
            <AnchorButton href="/tenants/new" variant="primary" size="sm">
              New client
            </AnchorButton>
            <AnchorButton href="/users/new" variant="outline" size="sm">
              New user
            </AnchorButton>
            <AnchorButton href="/calls" variant="ghost" size="sm">
              View calls
            </AnchorButton>
          </div>
        </Card>

        <Card>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            Operations
          </p>
          <div className="mt-3 flex flex-col gap-2">
            {[
              { label: "System Health", href: "/system-health" },
              { label: "Jobs & Workers", href: "/jobs" },
              { label: "Audit Logs", href: "/audit-logs" },
              { label: "Analytics", href: "/analytics" },
            ].map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="flex items-center justify-between border-b border-mist py-1.5 text-sm text-steel hover:text-graphite"
              >
                {link.label}
                <span className="text-xs text-slate-neutral">→</span>
              </a>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
