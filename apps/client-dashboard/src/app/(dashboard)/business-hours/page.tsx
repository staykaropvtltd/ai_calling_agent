"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";
import { PageHeader } from "../../../components/PageHeader";

export default function BusinessHoursPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <div>
        <PageHeader
          eyebrow="Management"
          title="Business Hours"
          description="Configure when your AI agent is active."
        />
        <FeaturePlaceholder
          icon="🕐"
          title="Business Hours not yet available"
          description="Define your hotel's operating hours, time zones, and holiday schedules to control when the AI agent accepts and places calls."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
