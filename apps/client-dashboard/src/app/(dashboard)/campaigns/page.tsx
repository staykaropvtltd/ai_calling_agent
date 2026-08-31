"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";
import { PageHeader } from "../../../components/PageHeader";

export default function CampaignsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <div>
        <PageHeader
          eyebrow="Management"
          title="Call Campaigns"
          description="Schedule and manage outbound calling campaigns."
        />
        <FeaturePlaceholder
          icon="📣"
          title="Campaigns not yet available"
          description="Create scheduled outbound campaigns to reach multiple guests automatically. Batch calling, follow-up sequences, and campaign analytics are coming."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
