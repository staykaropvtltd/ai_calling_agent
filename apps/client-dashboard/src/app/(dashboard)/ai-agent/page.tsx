"use client";

import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useClientProfileQuery } from "../../../lib/hooks/useSettings";
import { Card } from "../../../components/Card";
import { Spinner } from "../../../components/Spinner";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBadge } from "../../../components/StatusBadge";

export default function AIAgentPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <AIAgentDashboard />
    </RoleGuard>
  );
}

function AIAgentDashboard() {
  const { data: profile, isLoading } = useClientProfileQuery();

  const stack = [
    { label: "Telephony", value: "Exotel" },
    { label: "Speech-to-text", value: "Deepgram" },
    { label: "Language model", value: "Groq / LLaMA 3.3 70B" },
    { label: "Text-to-speech", value: "Deepgram Aura" },
  ];

  const callFlow = [
    "Guest calls your StayKaro phone number.",
    "The AI agent answers and greets by hotel name.",
    "Booking details are collected: name, dates, room type.",
    "The call is logged and your team is notified.",
    "Complex queries are escalated to a live agent.",
  ];

  return (
    <div>
      <PageHeader
        eyebrow="AI Agent"
        title="AI Voice Agent"
        description="Your hotel's AI agent configuration and infrastructure."
        actions={<StatusBadge value="active" />}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Voice stack */}
        <Card className="lg:col-span-2">
          <div className="mb-5 text-xs font-medium uppercase tracking-widest text-slate-neutral">
            Infrastructure
          </div>
          {isLoading ? (
            <Spinner />
          ) : (
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {stack.map(({ label, value }) => (
                <div key={label} className="rounded-xl border border-mist bg-fog px-4 py-3">
                  <dt className="text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
                    {label}
                  </dt>
                  <dd className="mt-1 font-display text-sm font-semibold text-graphite">
                    {value}
                  </dd>
                </div>
              ))}
              {profile && (
                <>
                  <div className="rounded-xl border border-mist bg-fog px-4 py-3">
                    <dt className="text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
                      Property
                    </dt>
                    <dd className="mt-1 font-display text-sm font-semibold text-graphite">
                      {profile.tenant_name}
                    </dd>
                  </div>
                  <div className="rounded-xl border border-mist bg-fog px-4 py-3">
                    <dt className="text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
                      Max concurrent calls
                    </dt>
                    <dd className="mt-1 font-display text-sm font-semibold text-graphite">
                      {profile.max_concurrent_calls ?? "—"}
                    </dd>
                  </div>
                </>
              )}
            </dl>
          )}
        </Card>

        {/* Call flow */}
        <Card tint="ivory">
          <div className="mb-4 text-xs font-medium uppercase tracking-widest text-brass">
            Call flow
          </div>
          <ol className="space-y-4">
            {callFlow.map((step, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-brass/30 bg-brass/10 text-[10px] font-bold text-brass">
                  {i + 1}
                </span>
                <span className="text-steel leading-relaxed">{step}</span>
              </li>
            ))}
          </ol>
        </Card>

        {/* Script & phone numbers */}
        <Card className="lg:col-span-2">
          <div className="mb-3 text-xs font-medium uppercase tracking-widest text-slate-neutral">
            Agent script
          </div>
          <p className="mb-4 text-sm text-steel">
            Your AI agent uses a hotel-specific script to handle guest
            interactions — confirming reservations, collecting check-in/out
            dates, and routing complex queries to your team.
          </p>
          <div className="rounded-xl border border-mist bg-fog px-4 py-3">
            <p className="text-xs text-slate-neutral">
              Script customisation is managed by StayKaro platform
              administrators. Contact{" "}
              <a
                href="mailto:support@staykaro.com"
                className="text-graphite underline"
              >
                support@staykaro.com
              </a>{" "}
              to update your script, greeting, or language settings.
            </p>
          </div>
        </Card>

        <Card>
          <div className="mb-3 text-xs font-medium uppercase tracking-widest text-slate-neutral">
            Phone numbers
          </div>
          <p className="mb-4 text-sm text-steel">
            Your assigned phone numbers are managed under{" "}
            <a href="/client/phone-numbers/" className="text-graphite underline">
              Phone Numbers
            </a>
            . Each number routes to a specific AI voice agent.
          </p>
          <p className="text-xs text-slate-neutral">
            Contact StayKaro to provision new numbers or change routing.
          </p>
        </Card>
      </div>
    </div>
  );
}
