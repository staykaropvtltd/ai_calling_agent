"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import {
  useDeleteTenant,
  useTenantQuery,
  useTenantStatsQuery,
  useUpdateTenant,
} from "../../../../lib/hooks/useTenants";
import { useUsersQuery } from "../../../../lib/hooks/useUsers";
import { Card, StatCard } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";
import { Table, type Column } from "../../../../components/Table";
import { FormField, inputClass } from "../../../../components/FormField";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";
import type { Tenant, TenantPlan, TenantStatus } from "../../../../lib/types/tenant";
import type { TenantUser } from "../../../../lib/types/user";

export default function TenantDetailPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <TenantDetail />
    </RoleGuard>
  );
}

function TenantDetail() {
  const params = useParams<{ id: string }>();
  const tenantId = params.id;
  const router = useRouter();

  const { data: tenant, isLoading, isError, error } = useTenantQuery(tenantId);
  const { data: stats } = useTenantStatsQuery(tenantId);
  const { data: users } = useUsersQuery({ tenant_id: tenantId, per_page: 50 });
  const updateTenant = useUpdateTenant(tenantId);
  const deleteTenant = useDeleteTenant();

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }
  if (isError || !tenant) {
    return <ErrorBanner error={error} />;
  }

  async function handleSuspend() {
    await deleteTenant.mutateAsync(tenantId);
    router.push("/tenants");
  }

  const userColumns: Column<TenantUser>[] = [
    {
      key: "email",
      header: "Email",
      render: (u) => <span className="font-medium text-graphite">{u.email}</span>,
    },
    { key: "full_name", header: "Name", render: (u) => u.full_name || "—" },
    { key: "role", header: "Role", render: (u) => <StatusBadge value={u.role} /> },
    { key: "status", header: "Status", render: (u) => <StatusBadge value={u.status} /> },
  ];

  return (
    <div className="max-w-3xl">
      <PageHeader
        eyebrow="Clients"
        title={tenant.name}
        description={`/${tenant.slug}`}
        actions={
          <Link href="/tenants">
            <Button variant="ghost" size="sm">← All clients</Button>
          </Link>
        }
      />

      {stats ? (
        <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Total calls" value={stats.total_calls} accent />
          <StatCard label="This month" value={stats.calls_this_month} />
          <StatCard label="Active users" value={stats.active_users} />
          <StatCard label="Plan usage" value={`${stats.plan_usage_pct}%`} />
        </div>
      ) : null}

      {/* Keyed by tenant_id so form state re-initialises from the loaded tenant */}
      <TenantEditForm
        key={tenant.tenant_id}
        tenant={tenant}
        onSave={(payload) => updateTenant.mutateAsync(payload)}
        onSuspend={handleSuspend}
        isSaving={updateTenant.isPending}
        saveError={updateTenant.error}
      />

      <div className="mt-8">
        <h2 className="mb-4 font-display text-lg font-semibold text-graphite">
          Users in this client
        </h2>
        <Card padding={false}>
          <Table
            columns={userColumns}
            rows={users?.data ?? []}
            rowKey={(u) => u.user_id}
            emptyMessage="No users in this client yet."
          />
        </Card>
      </div>
    </div>
  );
}

interface TenantEditFormProps {
  tenant: Tenant;
  onSave: (payload: {
    name: string;
    plan: TenantPlan;
    status: TenantStatus;
    contact_email: string;
    max_concurrent_calls: number;
  }) => Promise<unknown>;
  onSuspend: () => void;
  isSaving: boolean;
  saveError: unknown;
}

function TenantEditForm({ tenant, onSave, onSuspend, isSaving, saveError }: TenantEditFormProps) {
  const [name, setName] = useState(tenant.name);
  const [plan, setPlan] = useState<TenantPlan>(tenant.plan);
  const [status, setStatus] = useState<TenantStatus>(tenant.status);
  const [contactEmail, setContactEmail] = useState(tenant.contact_email ?? "");
  const [maxConcurrentCalls, setMaxConcurrentCalls] = useState(tenant.max_concurrent_calls ?? 10);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await onSave({ name, plan, status, contact_email: contactEmail, max_concurrent_calls: maxConcurrentCalls });
  }

  return (
    <Card>
      {saveError ? (
        <div className="mb-5">
          <ErrorBanner error={saveError} />
        </div>
      ) : null}
      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        <FormField label="Name" htmlFor="name">
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
        </FormField>
        <FormField label="Plan" htmlFor="plan">
          <select id="plan" value={plan} onChange={(e) => setPlan(e.target.value as TenantPlan)} className={inputClass}>
            <option value="starter">Starter</option>
            <option value="pro">Pro</option>
            <option value="enterprise">Enterprise</option>
          </select>
        </FormField>
        <FormField label="Status" htmlFor="status">
          <select id="status" value={status} onChange={(e) => setStatus(e.target.value as TenantStatus)} className={inputClass}>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="inactive">Inactive</option>
          </select>
        </FormField>
        <FormField label="Contact email" htmlFor="contact_email">
          <input
            id="contact_email"
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            className={inputClass}
          />
        </FormField>
        <FormField label="Max concurrent calls" htmlFor="max_calls">
          <input
            id="max_calls"
            type="number"
            min={1}
            value={maxConcurrentCalls}
            onChange={(e) => setMaxConcurrentCalls(Number(e.target.value))}
            className={inputClass}
          />
        </FormField>
        <div className="flex gap-3 pt-2">
          <button type="submit" disabled={isSaving} className="bg-graphite px-5 py-2.5 font-display text-sm font-medium text-white transition-colors hover:bg-steel disabled:opacity-50">
            {isSaving ? "Saving…" : "Save changes"}
          </button>
          <Button type="button" variant="danger" onClick={onSuspend}>
            Suspend client
          </Button>
        </div>
      </form>
    </Card>
  );
}
