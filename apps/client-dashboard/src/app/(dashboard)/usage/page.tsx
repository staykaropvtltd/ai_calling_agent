"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";
import { PageHeader } from "../../../components/PageHeader";

export default function UsagePage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <div>
        <PageHeader
          eyebrow="Account"
          title="Usage"
          description="Monitor your API usage and call volume against plan limits."
        />
        <FeaturePlaceholder
          icon="◎"
          title="Usage reporting not yet available"
          description="Detailed usage breakdowns, quota tracking, and historical consumption data are coming. Your current call count is visible on the Analytics page."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
