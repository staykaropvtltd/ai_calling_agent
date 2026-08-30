"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";
import { PageHeader } from "../../../components/PageHeader";

export default function BillingPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <div>
        <PageHeader
          eyebrow="Account"
          title="Billing & Plan"
          description="Your current plan, invoices, and payment methods."
        />
        <FeaturePlaceholder
          icon="◈"
          title="Billing not yet available"
          description="Plan management, invoice history, and payment configuration are coming. For billing enquiries contact support@staykaro.com."
          eta="Planned for Q2 2027"
        />
      </div>
    </RoleGuard>
  );
}
