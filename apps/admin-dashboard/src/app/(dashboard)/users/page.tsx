"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "../../../lib/auth/useAuth";
import { useUsersQuery } from "../../../lib/hooks/useUsers";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { StatusBadge } from "../../../components/StatusBadge";
import { PageHeader } from "../../../components/PageHeader";
import { AnchorButton } from "../../../components/Button";
import type { TenantUser } from "../../../lib/types/user";

const SELECT_CLASS =
  "rounded-xl border border-mist bg-canvas px-3 py-2 text-sm text-graphite focus:border-graphite focus:outline-none";

export default function UsersPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [tenantId, setTenantId] = useState("");

  const isSuperAdmin = user?.role === "super_admin";

  const { data, isLoading, isError, error } = useUsersQuery({
    page,
    per_page: 20,
    role: role || undefined,
    status: status || undefined,
    // tenant_admin tokens are scoped server-side regardless of this param
    tenant_id: isSuperAdmin ? tenantId || undefined : undefined,
  });

  const columns: Column<TenantUser>[] = [
    {
      key: "email",
      header: "Email",
      render: (u) => <span className="font-medium text-graphite">{u.email}</span>,
    },
    { key: "full_name", header: "Name", render: (u) => u.full_name || "—" },
    { key: "role", header: "Role", render: (u) => <StatusBadge value={u.role} /> },
    { key: "status", header: "Status", render: (u) => <StatusBadge value={u.status} /> },
    ...(isSuperAdmin
      ? [{ key: "tenant_id", header: "Tenant ID", render: (u: TenantUser) => <span className="font-mono text-xs text-slate-neutral">{u.tenant_id ?? "—"}</span> }]
      : []),
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Platform"
        title="Users"
        description="All users across all hotel clients."
        actions={
          isSuperAdmin ? (
            <AnchorButton href="/users/new">New user</AnchorButton>
          ) : undefined
        }
      />

      <div className="mb-5 flex flex-wrap gap-3">
        {isSuperAdmin ? (
          <input
            placeholder="Filter by tenant ID…"
            value={tenantId}
            onChange={(e) => { setTenantId(e.target.value); setPage(1); }}
            className="w-48 rounded-xl border border-mist bg-canvas px-4 py-2 text-sm text-graphite focus:border-graphite focus:outline-none placeholder:text-slate-neutral"
          />
        ) : null}
        <select value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }} className={SELECT_CLASS}>
          <option value="">All roles</option>
          <option value="tenant_admin">Tenant admin</option>
          <option value="agent">Agent</option>
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className={SELECT_CLASS}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
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
              rowKey={(u) => u.user_id}
              onRowClick={(u) => router.push(`/users/${u.user_id}`)}
              emptyMessage="No users yet."
            />
            <Pagination page={page} totalPages={data?.total_pages ?? 0} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
