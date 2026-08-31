"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function SettingsPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Settings"
          title="Platform Settings"
          description="Global configuration for the StayKaro platform."
        />
        <FeaturePlaceholder
          icon="◎"
          title="Platform settings coming soon"
          description="Global feature flags, rate limits, default AI configurations, notification settings, and API key management."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
