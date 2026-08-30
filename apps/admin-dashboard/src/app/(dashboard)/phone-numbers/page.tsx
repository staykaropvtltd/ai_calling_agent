"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function PhoneNumbersPage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Platform"
          title="Phone Numbers"
          description="Provision and assign telephone numbers to hotel clients."
        />
        <FeaturePlaceholder
          icon="◉"
          title="Phone number management coming soon"
          description="Provision DID numbers via Exotel or Twilio, assign them to tenants, and manage routing configuration."
          eta="Planned for Q4 2026"
        />
      </div>
    </RoleGuard>
  );
}
