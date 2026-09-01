"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useCampaignsQuery, useCreateCampaign, useUpdateCampaign } from "../../../lib/hooks/useCampaigns";
import { useClientLocale } from "../../../lib/hooks/useClientLocale";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { PageHeader } from "../../../components/PageHeader";
import { Button } from "../../../components/Button";
import { FormField, inputClass } from "../../../components/FormField";
import { StatusBadge } from "../../../components/StatusBadge";
import type { Campaign } from "../../../lib/types/campaign";

export default function CampaignsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <CampaignsList />
    </RoleGuard>
  );
}

function CampaignsList() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const { formatDateTime } = useClientLocale();
  const updateCampaign = useUpdateCampaign();

  const { data, isLoading, isError, error } = useCampaignsQuery({ page, per_page: 20 });

  const columns: Column<Campaign>[] = [
    {
      key: "name",
      header: "Campaign",
      render: (c) => (
        <div>
          <div className="font-medium text-graphite">{c.name}</div>
          {c.purpose && <div className="text-xs text-slate-neutral">{c.purpose}</div>}
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (c) => <StatusBadge value={c.status} />,
    },
    {
      key: "total_contacts",
      header: "Contacts",
      render: (c) => (
        <span className="font-medium text-graphite">{c.total_contacts}</span>
      ),
    },
    {
      key: "completed_count",
      header: "Completed",
      render: (c) => (
        <span className="text-emerald-700">{c.completed_count}</span>
      ),
    },
    {
      key: "failed_count",
      header: "Failed",
      render: (c) => (
        <span className={c.failed_count > 0 ? "text-red-600" : "text-slate-neutral"}>
          {c.failed_count}
        </span>
      ),
    },
    {
      key: "no_answer_count",
      header: "No Answer",
      render: (c) => <span className="text-slate-neutral">{c.no_answer_count}</span>,
    },
    {
      key: "created_at",
      header: "Created",
      render: (c) => (
        <span className="text-slate-neutral">{formatDateTime(c.created_at)}</span>
      ),
    },
    {
      key: "id",
      header: "Actions",
      render: (c) =>
        c.status === "draft" ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              updateCampaign.mutate({ id: c.id, status: "running" });
            }}
            className="text-xs font-medium text-ember hover:underline"
          >
            Start
          </button>
        ) : c.status === "running" ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              updateCampaign.mutate({ id: c.id, status: "paused" });
            }}
            className="text-xs font-medium text-amber-600 hover:underline"
          >
            Pause
          </button>
        ) : null,
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Campaigns"
        title="Call Campaigns"
        description="Schedule outbound calling campaigns to reach multiple guests."
        actions={
          <div className="flex items-center gap-2">
            <Link href="/upload">
              <Button variant="outline" size="sm">Upload sheet</Button>
            </Link>
            <Button variant="accent" onClick={() => setShowCreate((v) => !v)}>
              {showCreate ? "Cancel" : "+ New campaign"}
            </Button>
          </div>
        }
      />

      {showCreate && (
        <div className="mb-6">
          <CreateCampaignForm onSuccess={() => setShowCreate(false)} />
        </div>
      )}

      {updateCampaign.isError && (
        <div className="mb-4">
          <ErrorBanner error={updateCampaign.error} />
        </div>
      )}

      <Card padding={false}>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : isError ? (
          <div className="p-6">
            <ErrorBanner error={error} />
          </div>
        ) : (
          <>
            <Table
              columns={columns}
              rows={data?.data ?? []}
              rowKey={(c) => c.id}
              onRowClick={(c) => router.push(`/campaigns/${c.id}`)}
              emptyMessage="No campaigns yet. Create one to start bulk calling."
            />
            <Pagination
              page={page}
              totalPages={data?.total_pages ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>

      <div className="mt-4 rounded-lg border border-mist bg-fog px-4 py-3">
        <p className="text-xs text-slate-neutral">
          <strong className="text-steel">How campaigns work:</strong> Create a campaign, upload a
          contact sheet via{" "}
          <Link href="/upload" className="text-graphite underline">
            Sheet Upload
          </Link>
          , map columns to customer fields, then start the campaign. The system will queue calls for
          each contact. Call status updates in real time as the telephony provider reports results.
        </p>
      </div>
    </div>
  );
}

function CreateCampaignForm({ onSuccess }: { onSuccess: () => void }) {
  const createCampaign = useCreateCampaign();
  const [form, setForm] = useState({ name: "", purpose: "", description: "" });

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await createCampaign.mutateAsync({
      name: form.name,
      purpose: form.purpose || undefined,
      description: form.description || undefined,
    });
    setForm({ name: "", purpose: "", description: "" });
    onSuccess();
  }

  return (
    <Card>
      <div className="mb-4 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
        New campaign
      </div>
      {createCampaign.isError && (
        <div className="mb-4">
          <ErrorBanner error={createCampaign.error} />
        </div>
      )}
      <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <FormField label="Campaign name" htmlFor="campaign_name">
          <input
            id="campaign_name"
            required
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className={inputClass}
            placeholder="e.g. Pre-arrival confirmation"
          />
        </FormField>
        <FormField label="Purpose" htmlFor="campaign_purpose">
          <input
            id="campaign_purpose"
            value={form.purpose}
            onChange={(e) => setForm((f) => ({ ...f, purpose: e.target.value }))}
            className={inputClass}
            placeholder="e.g. Reservation confirmation"
          />
        </FormField>
        <FormField label="Description" htmlFor="campaign_description">
          <input
            id="campaign_description"
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            className={inputClass}
            placeholder="Optional notes"
          />
        </FormField>
        <div className="sm:col-span-3 flex justify-end">
          <Button type="submit" variant="accent" disabled={createCampaign.isPending}>
            {createCampaign.isPending ? "Creating…" : "Create campaign"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
