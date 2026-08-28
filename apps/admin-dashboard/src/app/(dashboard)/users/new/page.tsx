"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useCreateUser } from "../../../../lib/hooks/useUsers";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { buttonClass, FormField, inputClass, secondaryButtonClass } from "../../../../components/FormField";

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
      <h1 className="mb-6 text-xl font-semibold text-slate-900">New user</h1>
      <Card className="p-6">
        {createUser.isError ? (
          <div className="mb-4">
            <ErrorBanner error={createUser.error} />
          </div>
        ) : null}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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
            <select
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value as CreatableRole)}
              className={inputClass}
            >
              <option value="tenant_admin">Tenant admin</option>
              <option value="agent">Agent</option>
            </select>
          </FormField>
          <FormField label="Tenant ID" htmlFor="tenant_id">
            <input
              id="tenant_id"
              required
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              className={inputClass}
            />
          </FormField>
          <FormField label="Password (optional)" htmlFor="password">
            <input
              id="password"
              type="password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave blank — user can't log in until an admin sets one"
              className={inputClass}
            />
          </FormField>

          <div className="mt-2 flex gap-3">
            <button type="submit" disabled={createUser.isPending} className={buttonClass}>
              {createUser.isPending ? "Creating…" : "Create user"}
            </button>
            <button type="button" onClick={() => router.back()} className={secondaryButtonClass}>
              Cancel
            </button>
          </div>
        </form>
      </Card>
    </div>
  );
}
