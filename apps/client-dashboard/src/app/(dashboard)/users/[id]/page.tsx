"use client";

import type { ReactNode } from "react";
import { useParams } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useUserQuery } from "../../../../lib/hooks/useUsers";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";

export default function UserDetailPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <UserDetail />
    </RoleGuard>
  );
}

function UserDetail() {
  const params = useParams<{ id: string }>();
  const userId = params.id;

  const { data: targetUser, isLoading, isError, error } = useUserQuery(userId);

  if (isLoading) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }
  if (isError || !targetUser) {
    return <ErrorBanner error={error} />;
  }

  return (
    <div className="max-w-lg">
      <h1 className="mb-6 text-xl font-semibold text-slate-900">{targetUser.email}</h1>

      <Card className="p-6">
        {/* Read-only: creating/updating/deleting users is restricted to
            super_admin server-side (services/api/src/routers/admin.py),
            so a tenant_admin can only view its own tenant's users here. */}
        <dl className="flex flex-col gap-3 text-sm">
          <Row label="Full name" value={targetUser.full_name} />
          <Row label="Role" value={<StatusBadge value={targetUser.role} />} />
          <Row label="Status" value={<StatusBadge value={targetUser.status} />} />
          <Row label="Created" value={new Date(targetUser.created_at).toLocaleString()} />
        </dl>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-slate-100 pb-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-900">{value}</dd>
    </div>
  );
}
