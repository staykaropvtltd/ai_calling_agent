"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useTenantsQuery } from "../../../lib/hooks/useTenants";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { StatusBadge } from "../../../components/StatusBadge";
import { PageHeader } from "../../../components/PageHeader";
import { AnchorButton } from "../../../components/Button";
import type { Tenant } from "../../../lib/types/tenant";

const SELECT_CLASS =
  "rounded-xl border border-mist bg-canvas px-3 py-2 text-sm text-graphite focus:border-graphite focus:outline-none";

export default function TenantsPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <TenantsList />
    </RoleGuard>
  );
}

function TenantsList() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");

  const { data, isLoading, isError, error } = useTenantsQuery({
    page,
    per_page: 20,
    search: search || undefined,
    status: status || undefined,
  });

  const columns: Column<Tenant>[] = [
    {
      key: "name",
      header: "Client name",
      render: (t) => <span className="font-medium text-graphite">{t.name}</span>,
    },
    {
      key: "slug",
      header: "Slug",
      render: (t) => <span className="font-mono text-sm">{t.slug}</span>,
    },
    { key: "plan", header: "Plan", render: (t) => <StatusBadge value={t.plan} /> },
    { key: "status", header: "Status", render: (t) => <StatusBadge value={t.status} /> },
    {
      key: "max_calls",
      header: "Max concurrent",
      render: (t) => <span className="text-slate-neutral">{t.max_concurrent_calls}</span>,
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Platform"
        title="Hotel Clients"
        description="All tenants registered on StayKaro."
        actions={<AnchorButton href="/tenants/new">New client</AnchorButton>}
      />

      <div className="mb-5 flex flex-wrap gap-3">
        <input
          placeholder="Search by name…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="w-64 rounded-xl border border-mist bg-canvas px-4 py-2 text-sm text-graphite focus:border-graphite focus:outline-none placeholder:text-slate-neutral"
        />
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1); }}
          className={SELECT_CLASS}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

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
              rowKey={(t) => t.tenant_id}
              onRowClick={(t) => router.push(`/tenants/${t.tenant_id}`)}
              emptyMessage="No clients yet."
            />
            <Pagination page={page} totalPages={data?.total_pages ?? 0} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
