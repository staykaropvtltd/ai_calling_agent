"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function IntegrationsPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Platform"
          title="Integrations"
          description="Platform-level integration configuration and API credentials."
        />
        <FeaturePlaceholder
          icon="◈"
          title="Integration management coming soon"
          description="Configure and test platform integrations: Exotel, Twilio, Deepgram, PMS connectors, and webhook endpoints."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
