"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import {
  useDeleteTenant,
  useTenantQuery,
  useTenantStatsQuery,
  useUpdateTenant,
} from "../../../../lib/hooks/useTenants";
import { useUsersQuery } from "../../../../lib/hooks/useUsers";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";
import { Table, type Column } from "../../../../components/Table";
import { buttonClass, FormField, inputClass, secondaryButtonClass } from "../../../../components/FormField";
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
      <div className="flex justify-center py-10">
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
    { key: "email", header: "Email", render: (u) => u.email },
    { key: "full_name", header: "Name", render: (u) => u.full_name },
    { key: "role", header: "Role", render: (u) => <StatusBadge value={u.role} /> },
    { key: "status", header: "Status", render: (u) => <StatusBadge value={u.status} /> },
  ];

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{tenant.name}</h1>
        <p className="text-sm text-slate-500">/{tenant.slug}</p>
      </div>

      {stats ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Total calls" value={stats.total_calls} />
          <Stat label="This month" value={stats.calls_this_month} />
          <Stat label="Active users" value={stats.active_users} />
          <Stat label="Plan usage" value={`${stats.plan_usage_pct}%`} />
        </div>
      ) : null}

      {/* Keyed by tenant_id so the form's local state is (re)initialized
          fresh from the loaded tenant with no effect needed — see
          https://react.dev/learn/you-might-not-need-an-effect#resetting-all-state-when-a-prop-changes */}
      <TenantEditForm
        key={tenant.tenant_id}
        tenant={tenant}
        onSave={(payload) => updateTenant.mutateAsync(payload)}
        onSuspend={handleSuspend}
        isSaving={updateTenant.isPending}
        saveError={updateTenant.error}
      />

      <div>
        <h2 className="mb-3 text-lg font-medium text-slate-900">Users in this tenant</h2>
        <Card>
          <Table
            columns={userColumns}
            rows={users?.data ?? []}
            rowKey={(u) => u.user_id}
            emptyMessage="No users in this tenant yet."
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
    <Card className="p-6">
      {saveError ? (
        <div className="mb-4">
          <ErrorBanner error={saveError} />
        </div>
      ) : null}
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <FormField label="Name" htmlFor="name">
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
        </FormField>
        <FormField label="Plan" htmlFor="plan">
          <select
            id="plan"
            value={plan}
            onChange={(e) => setPlan(e.target.value as TenantPlan)}
            className={inputClass}
          >
            <option value="starter">Starter</option>
            <option value="pro">Pro</option>
            <option value="enterprise">Enterprise</option>
          </select>
        </FormField>
        <FormField label="Status" htmlFor="status">
          <select
            id="status"
            value={status}
            onChange={(e) => setStatus(e.target.value as TenantStatus)}
            className={inputClass}
          >
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
        <div className="mt-2 flex gap-3">
          <button type="submit" disabled={isSaving} className={buttonClass}>
            {isSaving ? "Saving…" : "Save changes"}
          </button>
          <button type="button" onClick={onSuspend} className={secondaryButtonClass}>
            Suspend tenant
          </button>
        </div>
      </form>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-900">{value}</div>
    </Card>
  );
}
