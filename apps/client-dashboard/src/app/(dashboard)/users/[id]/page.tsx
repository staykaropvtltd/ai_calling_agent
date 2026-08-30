"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useUserQuery } from "../../../../lib/hooks/useUsers";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";

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

  const { data: user, isLoading, isError, error } = useUserQuery(userId);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }
  if (isError || !user) {
    return (
      <div className="max-w-lg">
        <ErrorBanner error={error} />
      </div>
    );
  }

  return (
    <div className="max-w-lg">
      <PageHeader
        eyebrow="Users & Roles"
        title={user.full_name || user.email}
        actions={
          <Link href="/users">
            <Button variant="ghost" size="sm">
              ← All users
            </Button>
          </Link>
        }
      />

      {/* User management (create/update/suspend) is super_admin only server-side.
          Tenant admins can view their own tenant's users only. */}
      <Card>
        <dl className="divide-y divide-mist">
          <Row label="Email" value={<span className="font-mono text-sm">{user.email}</span>} />
          <Row label="Full name" value={user.full_name || "—"} />
          <Row label="Role" value={<StatusBadge value={user.role} />} />
          <Row label="Status" value={<StatusBadge value={user.status} />} />
          <Row
            label="Member since"
            value={new Date(user.created_at).toLocaleDateString(undefined, {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          />
        </dl>
      </Card>

      <p className="mt-4 text-xs text-slate-neutral">
        To change a user&apos;s role or suspend access, contact{" "}
        <a href="mailto:support@staykaro.com" className="text-graphite underline">
          support@staykaro.com
        </a>
        .
      </p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3">
      <dt className="text-xs font-medium uppercase tracking-widest text-slate-neutral">{label}</dt>
      <dd className="text-sm text-graphite">{value}</dd>
    </div>
  );
}
