"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function JobsPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Operations"
          title="Jobs & Workers"
          description="Background job queue, worker status, and task history."
        />
        <FeaturePlaceholder
          icon="◉"
          title="Jobs dashboard coming soon"
          description="Monitor call job queue depth, worker utilisation, failed jobs, and retry status across the platform."
          eta="Planned for Q4 2026"
        />
      </div>
    </RoleGuard>
  );
}
