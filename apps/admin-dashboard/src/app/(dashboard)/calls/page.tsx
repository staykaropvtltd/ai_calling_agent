"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../../lib/auth/useAuth";
import { useCallsQuery } from "../../../lib/hooks/useCalls";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { PageHeader } from "../../../components/PageHeader";
import type { CallLogEntry } from "../../../lib/types/call";

export default function CallsPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [tenantId, setTenantId] = useState("");

  const isSuperAdmin = user?.role === "super_admin";

  const { data, isLoading, isError, error } = useCallsQuery({
    page,
    per_page: 20,
    tenant_id: isSuperAdmin ? tenantId || undefined : undefined,
  });

  const columns: Column<CallLogEntry>[] = [
    {
      key: "customer_name",
      header: "Customer",
      render: (c) => <span className="font-medium text-graphite">{c.customer_name ?? "—"}</span>,
    },
    { key: "phone_number", header: "Phone", render: (c) => <span className="font-mono text-sm">{c.phone_number ?? "—"}</span> },
    { key: "hotel_name", header: "Hotel", render: (c) => c.hotel_name ?? "—" },
    { key: "check_in_date", header: "Check-in", render: (c) => c.check_in_date ?? "—" },
    { key: "check_out_date", header: "Check-out", render: (c) => c.check_out_date ?? "—" },
    {
      key: "created_at",
      header: "Created",
      render: (c) => c.created_at ? new Date(c.created_at).toLocaleString() : "—",
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Platform"
        title="Calls"
        description="All AI calls across the platform."
      />

      {isSuperAdmin ? (
        <div className="mb-5">
          <input
            placeholder="Filter by tenant ID…"
            value={tenantId}
            onChange={(e) => { setTenantId(e.target.value); setPage(1); }}
            className="w-56 rounded-xl border border-mist bg-canvas px-4 py-2 text-sm text-graphite focus:border-graphite focus:outline-none placeholder:text-slate-neutral"
          />
        </div>
      ) : null}

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
              rowKey={(c) => String(c.id)}
              onRowClick={(c) => router.push(`/calls/${c.id}`)}
              emptyMessage="No calls yet."
            />
            <Pagination page={page} totalPages={data?.total_pages ?? 0} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
