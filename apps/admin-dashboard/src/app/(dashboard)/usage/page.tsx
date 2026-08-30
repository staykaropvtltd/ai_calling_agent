"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function UsagePage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Analytics"
          title="Usage"
          description="Per-tenant usage breakdown, quota tracking, and billing data."
        />
        <FeaturePlaceholder
          icon="◎"
          title="Usage reporting not yet available"
          description="Per-tenant call counts, API usage, concurrent call peaks, and cost attribution will be visible here."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
