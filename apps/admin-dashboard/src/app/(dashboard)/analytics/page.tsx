"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function AnalyticsPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Analytics"
          title="Platform Analytics"
          description="Aggregate call metrics, tenant usage, and AI performance across all hotel clients."
        />
        <FeaturePlaceholder
          icon="◈"
          title="Platform analytics coming soon"
          description="Cross-tenant call volume, success rates, AI performance benchmarks, and regional breakdowns will be available here."
          eta="Planned for Q4 2026"
        />
      </div>
    </RoleGuard>
  );
}
