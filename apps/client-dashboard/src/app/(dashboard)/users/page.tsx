"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useUsersQuery } from "../../../lib/hooks/useUsers";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { StatusBadge } from "../../../components/StatusBadge";
import { PageHeader } from "../../../components/PageHeader";
import type { TenantUser } from "../../../lib/types/user";

const SELECT_CLASS =
  "rounded-xl border border-mist bg-canvas px-3 py-2 text-sm text-graphite focus:border-graphite focus:outline-none";

export default function UsersPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <UsersList />
    </RoleGuard>
  );
}

function UsersList() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");

  const { data, isLoading, isError, error } = useUsersQuery({
    page,
    per_page: 20,
    role: role || undefined,
    status: status || undefined,
  });

  const columns: Column<TenantUser>[] = [
    {
      key: "email",
      header: "Email",
      render: (u) => <span className="font-medium text-graphite">{u.email}</span>,
    },
    {
      key: "full_name",
      header: "Name",
      render: (u) => <span className="text-steel">{u.full_name || "—"}</span>,
    },
    {
      key: "role",
      header: "Role",
      render: (u) => <StatusBadge value={u.role} />,
    },
    {
      key: "status",
      header: "Status",
      render: (u) => <StatusBadge value={u.status} />,
    },
  ];

  function handleRoleChange(val: string) {
    setRole(val);
    setPage(1);
  }

  function handleStatusChange(val: string) {
    setStatus(val);
    setPage(1);
  }

  return (
    <div>
      <PageHeader
        eyebrow="Management"
        title="Users & Roles"
        description="Manage who has access to this hotel's dashboard."
      />

      <div className="mb-5 flex flex-wrap gap-3">
        <select value={role} onChange={(e) => handleRoleChange(e.target.value)} className={SELECT_CLASS}>
          <option value="">All roles</option>
          <option value="tenant_admin">Admin</option>
          <option value="agent">Agent</option>
        </select>
        <select value={status} onChange={(e) => handleStatusChange(e.target.value)} className={SELECT_CLASS}>
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
              emptyMessage="No users found."
            />
            <Pagination page={page} totalPages={data?.total_pages ?? 0} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
