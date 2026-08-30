"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { PageHeader } from "../../../components/PageHeader";
import { FeaturePlaceholder } from "../../../components/FeaturePlaceholder";

export default function AIVoicePage() {
  return (
    <RoleGuard allowedRoles={["super_admin"]}>
      <div>
        <PageHeader
          eyebrow="Platform"
          title="AI / Voice"
          description="Manage LLM models, speech engines, and voice profiles."
        />
        <FeaturePlaceholder
          icon="◎"
          title="AI configuration management coming soon"
          description="Configure Groq/LLaMA model settings, Deepgram STT parameters, TTS voice profiles, and per-tenant AI overrides."
          eta="Planned for Q1 2027"
        />
      </div>
    </RoleGuard>
  );
}
