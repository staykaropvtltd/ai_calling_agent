"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useCreateUser } from "../../../../lib/hooks/useUsers";
import { useTenantsQuery } from "../../../../lib/hooks/useTenants";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { FormField, inputClass } from "../../../../components/FormField";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";

type CreatableRole = "tenant_admin" | "agent";

export default function NewUserPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <NewUserForm />
    </RoleGuard>
  );
}

function NewUserForm() {
  const router = useRouter();
  const createUser = useCreateUser();

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<CreatableRole>("agent");
  const [tenantId, setTenantId] = useState("");
  const [password, setPassword] = useState("");

  const { data: tenantsData, isLoading: tenantsLoading } = useTenantsQuery({ per_page: 100 });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const created = await createUser.mutateAsync({
      email,
      full_name: fullName,
      role,
      tenant_id: tenantId,
      ...(password ? { password } : {}),
    });
    router.push(`/users/${created.user_id}`);
  }

  return (
    <div className="max-w-lg">
      <PageHeader eyebrow="Users" title="New user" />

      <Card>
        {createUser.isError ? (
          <div className="mb-5">
            <ErrorBanner error={createUser.error} />
          </div>
        ) : null}
        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <FormField label="Email" htmlFor="email">
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </FormField>
          <FormField label="Full name" htmlFor="full_name">
            <input
              id="full_name"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className={inputClass}
            />
          </FormField>
          <FormField label="Role" htmlFor="role">
            <select id="role" value={role} onChange={(e) => setRole(e.target.value as CreatableRole)} className={inputClass}>
              <option value="tenant_admin">Tenant admin</option>
              <option value="agent">Agent</option>
            </select>
          </FormField>
          <FormField label="Tenant" htmlFor="tenant_id">
            <select
              id="tenant_id"
              required
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              className={inputClass}
              disabled={tenantsLoading}
            >
              <option value="">
                {tenantsLoading ? "Loading tenants…" : "Select a tenant…"}
              </option>
              {tenantsData?.data.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.name} ({t.slug})
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Password (optional)" htmlFor="password">
            <input
              id="password"
              type="password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave blank until admin sets one"
              className={inputClass}
            />
          </FormField>

          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={createUser.isPending}
              className="bg-graphite px-5 py-2.5 font-display text-sm font-medium text-white transition-colors hover:bg-steel disabled:opacity-50"
            >
              {createUser.isPending ? "Creating…" : "Create user"}
            </button>
            <Button type="button" variant="ghost" onClick={() => router.back()}>
              Cancel
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
