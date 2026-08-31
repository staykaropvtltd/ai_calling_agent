"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useCreateTenant } from "../../../../lib/hooks/useTenants";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { FormField, inputClass } from "../../../../components/FormField";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";
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
      <PageHeader eyebrow="Clients" title="New hotel client" />

      <Card>
        {createTenant.isError ? (
          <div className="mb-5">
            <ErrorBanner error={createTenant.error} />
          </div>
        ) : null}
        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <FormField label="Name" htmlFor="name">
            <input
              id="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Grand Palace Hotel"
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
              placeholder="grand-palace"
              className={inputClass}
            />
          </FormField>
          <FormField label="Plan" htmlFor="plan">
            <select id="plan" value={plan} onChange={(e) => setPlan(e.target.value as TenantPlan)} className={inputClass}>
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

          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={createTenant.isPending}
              className="bg-graphite px-5 py-2.5 font-display text-sm font-medium text-white transition-colors hover:bg-steel disabled:opacity-50"
            >
              {createTenant.isPending ? "Creating…" : "Create client"}
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
