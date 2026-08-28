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
import { buttonClass, inputClass } from "../../../components/FormField";
import type { TenantUser } from "../../../lib/types/user";

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
    // (services/api/src/routers/admin.py's list_users ignores it for them).
    tenant_id: isSuperAdmin ? tenantId || undefined : undefined,
  });

  const columns: Column<TenantUser>[] = [
    { key: "email", header: "Email", render: (u) => u.email },
    { key: "full_name", header: "Name", render: (u) => u.full_name },
    { key: "role", header: "Role", render: (u) => <StatusBadge value={u.role} /> },
    { key: "status", header: "Status", render: (u) => <StatusBadge value={u.status} /> },
    ...(isSuperAdmin
      ? [{ key: "tenant_id", header: "Tenant ID", render: (u: TenantUser) => u.tenant_id ?? "—" }]
      : []),
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Users</h1>
        {isSuperAdmin ? (
          <Link href="/users/new" className={buttonClass}>
            New user
          </Link>
        ) : null}
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        {isSuperAdmin ? (
          <input
            placeholder="Filter by tenant ID…"
            value={tenantId}
            onChange={(e) => {
              setTenantId(e.target.value);
              setPage(1);
            }}
            className={`${inputClass} w-48`}
          />
        ) : null}
        <select
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setPage(1);
          }}
          className={inputClass}
        >
          <option value="">All roles</option>
          <option value="tenant_admin">Tenant admin</option>
          <option value="agent">Agent</option>
        </select>
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
