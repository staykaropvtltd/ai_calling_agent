"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function SystemHealthPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Operations"
          title="System Health"
          description="Service uptime, error rates, and infrastructure metrics."
        />
        <FeaturePlaceholder
          icon="◎"
          title="System health dashboard coming soon"
          description="Real-time service health, API error rates, database performance, Redis queue depth, and third-party integration status."
          eta="Planned for Q4 2026"
        />
      </div>
    </RoleGuard>
  );
}
