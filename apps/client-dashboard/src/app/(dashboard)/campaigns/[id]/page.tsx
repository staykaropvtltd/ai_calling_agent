"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useCampaignQuery, useUpdateCampaign } from "../../../../lib/hooks/useCampaigns";
import { useClientLocale } from "../../../../lib/hooks/useClientLocale";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";
import { Button } from "../../../../components/Button";

export default function CampaignDetailPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <CampaignDetail />
    </RoleGuard>
  );
}

function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  // Poll every 5 seconds while the campaign is active so counters update in real time.
  const { data: campaign, isLoading, isError, error, refetch } = useCampaignQuery(id, {
    refetchInterval: 5000,
  });
  const updateCampaign = useUpdateCampaign();
  const { formatDateTime } = useClientLocale();

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (isError || !campaign) {
    return <ErrorBanner error={error} />;
  }

  const completionPct =
    campaign.total_contacts > 0
      ? Math.round(
          ((campaign.completed_count + campaign.failed_count + campaign.no_answer_count) /
            campaign.total_contacts) *
            100,
        )
      : 0;

  function handleAction(newStatus: string) {
    if (!campaign) return;
    updateCampaign.mutate(
      { id: campaign.id, status: newStatus },
      { onSuccess: () => refetch() },
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="mb-1 text-xs text-slate-neutral">
            <Link href="/campaigns" className="hover:underline">
              Campaigns
            </Link>{" "}
            /
          </div>
          <h1 className="text-2xl font-semibold text-graphite">{campaign.name}</h1>
          {campaign.purpose && (
            <p className="mt-1 text-sm text-steel">{campaign.purpose}</p>
          )}
        </div>
        <div className="flex items-center gap-2 pt-1">
          <StatusBadge value={campaign.status} />
          {campaign.status === "draft" && (
            <Button
              variant="accent"
              size="sm"
              onClick={() => handleAction("running")}
              disabled={updateCampaign.isPending}
            >
              Start campaign
            </Button>
          )}
          {campaign.status === "running" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleAction("paused")}
              disabled={updateCampaign.isPending}
            >
              Pause
            </Button>
          )}
          {campaign.status === "paused" && (
            <Button
              variant="accent"
              size="sm"
              onClick={() => handleAction("running")}
              disabled={updateCampaign.isPending}
            >
              Resume
            </Button>
          )}
        </div>
      </div>

      {updateCampaign.isError && <ErrorBanner error={updateCampaign.error} />}

      {/* Progress */}
      <Card>
        <div className="mb-4 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
          Progress
        </div>
        <div className="mb-3 h-2 overflow-hidden rounded-full bg-fog">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${completionPct}%` }}
          />
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Stat label="Total" value={campaign.total_contacts} />
          <Stat label="Queued" value={campaign.queued_count} color="text-blue-600" />
          <Stat label="Completed" value={campaign.completed_count} color="text-emerald-700" />
          <Stat
            label="Failed"
            value={campaign.failed_count}
            color={campaign.failed_count > 0 ? "text-red-600" : undefined}
          />
          <Stat label="No Answer" value={campaign.no_answer_count} />
        </div>
      </Card>

      {/* Configuration */}
      <Card>
        <div className="mb-4 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
          Configuration
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm sm:grid-cols-4">
          <Detail label="Max retries" value={String(campaign.max_retries)} />
          <Detail
            label="Retry delay"
            value={`${campaign.retry_delay_minutes} min`}
          />
          <Detail
            label="Scheduled"
            value={campaign.scheduled_at ? formatDateTime(campaign.scheduled_at) : "Manual start"}
          />
          <Detail
            label="Created"
            value={campaign.created_at ? formatDateTime(campaign.created_at) : "—"}
          />
        </dl>
        {campaign.description && (
          <p className="mt-4 text-sm text-steel">{campaign.description}</p>
        )}
      </Card>

      {/* Actions */}
      <div className="flex gap-3">
        <Link href="/upload">
          <Button variant="outline" size="sm">
            Upload more contacts
          </Button>
        </Link>
        <Link href="/campaigns">
          <Button variant="ghost" size="sm">
            Back to campaigns
          </Button>
        </Link>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <div>
      <div className={`text-2xl font-semibold ${color ?? "text-graphite"}`}>{value}</div>
      <div className="text-xs text-slate-neutral">{label}</div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-widest text-slate-neutral">{label}</dt>
      <dd className="mt-0.5 text-graphite">{value}</dd>
    </div>
  );
}
