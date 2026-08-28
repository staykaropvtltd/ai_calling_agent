"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useCreateTenant } from "../../../../lib/hooks/useTenants";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { buttonClass, FormField, inputClass, secondaryButtonClass } from "../../../../components/FormField";
import type { TenantPlan } from "../../../../lib/types/tenant";

export default function NewTenantPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <NewTenantForm />
    </RoleGuard>
  );
}

function NewTenantForm() {
  const router = useRouter();
  const createTenant = useCreateTenant();

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [plan, setPlan] = useState<TenantPlan>("starter");
  const [contactEmail, setContactEmail] = useState("");
  const [maxConcurrentCalls, setMaxConcurrentCalls] = useState(10);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const tenant = await createTenant.mutateAsync({
      name,
      slug,
      plan,
      contact_email: contactEmail,
      max_concurrent_calls: maxConcurrentCalls,
    });
    router.push(`/tenants/${tenant.tenant_id}`);
  }

  return (
    <div className="max-w-lg">
      <h1 className="mb-6 text-xl font-semibold text-slate-900">New tenant</h1>
      <Card className="p-6">
        {createTenant.isError ? (
          <div className="mb-4">
            <ErrorBanner error={createTenant.error} />
          </div>
        ) : null}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FormField label="Name" htmlFor="name">
            <input
              id="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
            />
          </FormField>
          <FormField label="Slug" htmlFor="slug">
            <input
              id="slug"
              required
              pattern="[a-z0-9-]+"
              title="Lowercase letters, numbers and hyphens only"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className={inputClass}
            />
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
          <FormField label="Contact email" htmlFor="contact_email">
            <input
              id="contact_email"
              type="email"
              required
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
              required
              value={maxConcurrentCalls}
              onChange={(e) => setMaxConcurrentCalls(Number(e.target.value))}
              className={inputClass}
            />
          </FormField>

          <div className="mt-2 flex gap-3">
            <button type="submit" disabled={createTenant.isPending} className={buttonClass}>
              {createTenant.isPending ? "Creating…" : "Create tenant"}
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
