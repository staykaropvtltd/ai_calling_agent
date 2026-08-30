"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { Card } from "../../../components/Card";
import { StatusBadge } from "../../../components/StatusBadge";
import { PageHeader } from "../../../components/PageHeader";

interface Integration {
  name: string;
  description: string;
  category: string;
  status: "active" | "available" | "coming_soon";
}

const INTEGRATIONS: Integration[] = [
  {
    name: "Exotel",
    description: "Telephony provider for outbound AI calling in India and Southeast Asia.",
    category: "Telephony",
    status: "active",
  },
  {
    name: "Twilio",
    description: "Global telephony provider supporting 180+ countries.",
    category: "Telephony",
    status: "available",
  },
  {
    name: "Deepgram",
    description: "Real-time speech-to-text transcription powering AI call comprehension.",
    category: "AI / Speech",
    status: "active",
  },
  {
    name: "Groq + LLaMA 3.3",
    description: "Ultra-fast LLM inference for real-time AI agent responses.",
    category: "AI / Speech",
    status: "active",
  },
  {
    name: "Property Management System (PMS)",
    description: "Sync guest reservations and check-in data directly from your PMS.",
    category: "Hotel Systems",
    status: "coming_soon",
  },
  {
    name: "CRM Integration",
    description: "Push call outcomes and guest profiles to your CRM automatically.",
    category: "CRM",
    status: "coming_soon",
  },
  {
    name: "WhatsApp Business",
    description: "Follow-up messages and confirmations via WhatsApp after AI calls.",
    category: "Messaging",
    status: "coming_soon",
  },
  {
    name: "n8n Workflows",
    description: "Custom automation workflows triggered by call events.",
    category: "Automation",
    status: "coming_soon",
  },
];

export default function IntegrationsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <IntegrationsView />
    </RoleGuard>
  );
}

function IntegrationsView() {
  const categories = [...new Set(INTEGRATIONS.map((i) => i.category))];

  return (
    <div>
      <PageHeader
        eyebrow="Management"
        title="Integrations"
        description="Services connected to your AI calling infrastructure."
      />

      <div className="space-y-8">
        {categories.map((cat) => {
          const items = INTEGRATIONS.filter((i) => i.category === cat);
          return (
            <section key={cat}>
              <h2 className="mb-3 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
                {cat}
              </h2>
              <div className="grid gap-4 sm:grid-cols-2">
                {items.map((integration) => (
                  <IntegrationCard key={integration.name} integration={integration} />
                ))}
              </div>
            </section>
          );
        })}

        <Card tint="ivory">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-graphite">Request an integration</p>
            <p className="text-sm text-steel">
              Need a custom integration with your hotel system or CRM? Contact{" "}
              <a href="mailto:support@staykaro.com" className="text-graphite underline">
                support@staykaro.com
              </a>{" "}
              and our team will assess your requirements.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}

function IntegrationCard({ integration }: { integration: Integration }) {
  return (
    <Card>
      <div className="mb-2 flex items-start justify-between gap-3">
        <p className="font-display font-medium text-graphite">{integration.name}</p>
        <StatusBadge value={integration.status} />
      </div>
      <p className="text-sm text-steel">{integration.description}</p>
      {integration.status === "active" && (
        <p className="mt-3 text-xs text-slate-neutral">Managed by StayKaro.</p>
      )}
      {integration.status === "available" && (
        <p className="mt-3 text-xs text-graphite">
          Contact support to enable for your account.
        </p>
      )}
    </Card>
  );
}
