"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useTenantsQuery } from "../../../lib/hooks/useTenants";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { StatusBadge } from "../../../components/StatusBadge";
import { buttonClass, inputClass } from "../../../components/FormField";
import type { Tenant } from "../../../lib/types/tenant";

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
    { key: "name", header: "Name", render: (t) => t.name },
    { key: "slug", header: "Slug", render: (t) => t.slug },
    { key: "plan", header: "Plan", render: (t) => <StatusBadge value={t.plan} /> },
    { key: "status", header: "Status", render: (t) => <StatusBadge value={t.status} /> },
    { key: "max_calls", header: "Max concurrent calls", render: (t) => t.max_concurrent_calls },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Tenants</h1>
        <Link href="/tenants/new" className={buttonClass}>
          New tenant
        </Link>
      </div>

      <div className="mb-4 flex gap-3">
        <input
          placeholder="Search by name…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className={`${inputClass} w-64`}
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className={inputClass}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

      <Card>
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : isError ? (
          <div className="p-4">
            <ErrorBanner error={error} />
          </div>
        ) : (
          <>
            <Table
              columns={columns}
              rows={data?.data ?? []}
              rowKey={(t) => t.tenant_id}
              onRowClick={(t) => router.push(`/tenants/${t.tenant_id}`)}
              emptyMessage="No tenants yet."
            />
            <Pagination page={page} totalPages={data?.total_pages ?? 0} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
