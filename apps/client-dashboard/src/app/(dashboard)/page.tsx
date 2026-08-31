"use client";

import Link from "next/link";
import { useAuth } from "../../lib/auth/useAuth";
import { useAnalyticsQuery } from "../../lib/hooks/useAnalytics";
import { useCallsQuery } from "../../lib/hooks/useCalls";
import { useClientLocale } from "../../lib/hooks/useClientLocale";
import { Card, StatCard } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { StatusBadge } from "../../components/StatusBadge";
import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";

export default function OverviewPage() {
  const { user } = useAuth();
  const isTenantAdmin = user?.role === "tenant_admin";
  const { formatDateTime } = useClientLocale();

  const analytics = useAnalyticsQuery({ enabled: isTenantAdmin });
  const recentCalls = useCallsQuery({ page: 1, per_page: 8 }, { enabled: !!user });

  return (
    <div>
      <PageHeader
        eyebrow="Dashboard"
        title={`Welcome back, ${user?.full_name?.split(" ")[0] ?? "there"}`}
        description={isTenantAdmin ? "Here's your hotel's AI calling overview." : "Place calls and track your recent activity."}
        actions={
          <Link href="/calls/new">
            <Button variant="accent" size="md">New Call</Button>
          </Link>
        }
      />

      {isTenantAdmin ? (
        <div className="space-y-6">
          {/* Asymmetric stats row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="lg:col-span-2">
              <StatCard
                label="Total calls"
                value={
                  analytics.isLoading
                    ? "—"
                    : analytics.isError
                      ? "—"
                      : String(analytics.data?.total_calls ?? 0)
                }
                sub={analytics.data ? "All time" : undefined}
                accent
              />
            </div>
            <StatCard
              label="This month"
              value={analytics.isLoading ? "—" : String(analytics.data?.calls_this_month ?? 0)}
            />
            <StatCard
              label="Last 7 days"
              value={analytics.isLoading ? "—" : String(analytics.data?.calls_this_week ?? 0)}
            />
          </div>

          {/* Analytics shortcut + recent calls */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {/* Featured: analytics link */}
            <Card tint="ivory" className="lg:col-span-1 flex flex-col justify-between">
              <div>
                <div className="mb-1 text-[11px] font-medium uppercase tracking-widest text-brass">
                  Analytics
                </div>
                <h2 className="font-display text-lg font-semibold tracking-display text-graphite">
                  View call volume trends
                </h2>
                <p className="mt-2 text-sm text-steel">
                  30-day daily breakdown, total stats, and call patterns.
                </p>
              </div>
              <div className="mt-6">
                <Link href="/analytics">
                  <Button variant="outline" size="sm">Open analytics →</Button>
                </Link>
              </div>
            </Card>

            {/* Recent calls */}
            <Card padding={false} className="lg:col-span-2 overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-mist">
                <h2 className="font-display text-sm font-semibold text-graphite">Recent calls</h2>
                <Link href="/calls" className="text-xs text-slate-neutral hover:text-graphite transition-colors">
                  View all →
                </Link>
              </div>
              <RecentCallsList recentCalls={recentCalls} formatDateTime={formatDateTime} />
            </Card>
          </div>
        </div>
      ) : (
        // Agent view
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Card tint="ivory" className="flex flex-col gap-4">
              <div>
                <div className="mb-1 text-[11px] font-medium uppercase tracking-widest text-brass">
                  Quick action
                </div>
                <h2 className="font-display text-lg font-semibold tracking-display text-graphite">
                  Place an AI call
                </h2>
                <p className="mt-2 text-sm text-steel">
                  Submit a reservation request and let the AI agent handle the call.
                </p>
              </div>
              <div>
                <Link href="/calls/new">
                  <Button variant="accent">New Call</Button>
                </Link>
              </div>
            </Card>

            <Card padding={false} className="overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-mist">
                <h2 className="font-display text-sm font-semibold text-graphite">Recent calls</h2>
                <Link href="/calls" className="text-xs text-slate-neutral hover:text-graphite transition-colors">
                  View all →
                </Link>
              </div>
              <RecentCallsList recentCalls={recentCalls} formatDateTime={formatDateTime} />
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function RecentCallsList({
  recentCalls,
  formatDateTime,
}: {
  recentCalls: ReturnType<typeof useCallsQuery>;
  formatDateTime: (iso: string | null | undefined) => string;
}) {
  if (recentCalls.isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner />
      </div>
    );
  }
  if (!recentCalls.data?.data.length) {
    return (
      <p className="py-8 text-center text-sm text-slate-neutral">No calls yet.</p>
    );
  }
  return (
    <ul>
      {recentCalls.data.data.map((c, i) => (
        <li
          key={c.id}
          className={`border-b border-mist/60 px-6 py-3 last:border-0 ${
            i % 2 === 0 ? "bg-canvas" : "bg-fog/30"
          }`}
        >
          <Link
            href={`/calls/${c.id}`}
            className="flex items-center justify-between hover:opacity-70 transition-opacity"
          >
            <div className="min-w-0">
              <div className="font-medium text-graphite text-sm truncate">
                {c.customer_name ?? "—"}
              </div>
              <div className="text-xs text-slate-neutral">{c.phone_number ?? "—"}</div>
            </div>
            <div className="ml-4 shrink-0 text-right">
              <StatusBadge value={c.status ?? "pending"} />
              <div className="mt-0.5 text-[10px] text-slate-neutral">
                {formatDateTime(c.created_at)}
              </div>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
