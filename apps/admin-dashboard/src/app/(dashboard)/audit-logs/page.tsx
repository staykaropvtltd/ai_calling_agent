"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function AuditLogsPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Operations"
          title="Audit Logs"
          description="Admin actions, tenant changes, and security events."
        />
        <FeaturePlaceholder
          icon="◈"
          title="Audit logs not yet available"
          description="Immutable record of platform admin actions: tenant creation, user suspension, permission changes, and API access events."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
