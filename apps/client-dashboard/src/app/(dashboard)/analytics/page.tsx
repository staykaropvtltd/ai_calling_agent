"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useAnalyticsQuery } from "../../../lib/hooks/useAnalytics";
import { Card, StatCard } from "../../../components/Card";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { PageHeader } from "../../../components/PageHeader";
import type { CallVolumeDay } from "../../../lib/types/analytics";

export default function AnalyticsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <AnalyticsDashboard />
    </RoleGuard>
  );
}

function AnalyticsDashboard() {
  const { data, isLoading, isError, error } = useAnalyticsQuery();

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );
  }
  if (isError) {
    return <ErrorBanner error={error} />;
  }
  if (!data) return null;

  const maxDayCount = Math.max(...data.daily_volume.map((d) => d.count), 1);

  return (
    <div>
      <PageHeader
        eyebrow="Analytics"
        title="Call Analytics"
        description="Call volume and trends for your property."
      />

      <div className="space-y-6">
        {/* Asymmetric stat row */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard label="Total calls" value={data.total_calls} accent />
          <StatCard label="This month" value={data.calls_this_month} />
          <StatCard label="Last 7 days" value={data.calls_this_week} />
        </div>

        {/* Daily volume */}
        <Card>
          <div className="mb-6 flex items-center justify-between">
            <h2 className="font-display text-sm font-semibold tracking-display text-graphite">
              Call volume — last 30 days
            </h2>
            <span className="text-xs text-slate-neutral">{data.daily_volume.length} days</span>
          </div>
          {data.daily_volume.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-neutral">
              No calls in the last 30 days.
            </p>
          ) : (
            <div className="space-y-1.5">
              {data.daily_volume.map((day) => (
                <DayBar key={day.date} day={day} max={maxDayCount} />
              ))}
            </div>
          )}
        </Card>

        <p className="text-xs text-slate-neutral">
          Data reflects outbound call requests logged via the StayKaro API. Each
          row represents one submitted call request; call outcomes require the
          voice pipeline to be active.
        </p>
      </div>
    </div>
  );
}

function DayBar({ day, max }: { day: CallVolumeDay; max: number }) {
  const widthPct = Math.max((day.count / max) * 100, day.count > 0 ? 1.5 : 0);
  return (
    <div className="flex items-center gap-4 text-xs">
      <span className="w-24 shrink-0 text-right tabular-nums text-slate-neutral">
        {day.date}
      </span>
      <div className="flex-1">
        <div
          className="h-3.5 rounded-sm bg-graphite/80 transition-all"
          style={{ width: `${widthPct}%` }}
          title={`${day.count} call${day.count === 1 ? "" : "s"}`}
        />
      </div>
      <span className="w-8 shrink-0 tabular-nums text-steel">{day.count}</span>
    </div>
  );
}
