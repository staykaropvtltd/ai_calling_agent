"use client";

import type { ReactNode } from "react";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useAuth } from "../../../lib/auth/useAuth";
import { useClientProfileQuery } from "../../../lib/hooks/useSettings";
import { Card } from "../../../components/Card";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { StatusBadge } from "../../../components/StatusBadge";
import { PageHeader } from "../../../components/PageHeader";

export default function SettingsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <Settings />
    </RoleGuard>
  );
}

function Settings() {
  const { user } = useAuth();
  const { data: profile, isLoading, isError, error } = useClientProfileQuery();

  if (isLoading) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="Account"
        title="Settings"
        description="Your account and organisation configuration."
      />

      <div className="max-w-2xl space-y-5">
        {/* Account */}
        <Card>
          <SectionHeading label="Your account" />
          <dl className="divide-y divide-mist">
            <Row label="Name" value={user?.full_name ?? "—"} />
            <Row label="Email" value={user?.email ?? "—"} />
            <Row label="Role" value={<StatusBadge value={user?.role ?? null} />} />
          </dl>
        </Card>

        {/* Organisation */}
        <Card>
          <div className="mb-5 flex items-start justify-between">
            <SectionHeading label="Organisation" />
            <span className="text-xs text-slate-neutral">
              Contact StayKaro support to update
            </span>
          </div>

          {isError ? (
            <ErrorBanner error={error} />
          ) : !profile ? null : (
            <dl className="divide-y divide-mist">
              <Row label="Name" value={profile.tenant_name} />
              <Row label="Slug" value={profile.tenant_slug ?? "—"} />
              <Row label="Plan" value={<StatusBadge value={profile.plan} />} />
              <Row label="Status" value={<StatusBadge value={profile.tenant_status} />} />
              <Row label="Contact email" value={profile.contact_email ?? "—"} />
              <Row label="Contact phone" value={profile.contact_phone ?? "—"} />
              <Row label="Max concurrent calls" value={String(profile.max_concurrent_calls ?? "—")} />
              <Row label="API call limit" value={String(profile.api_limit ?? "—")} />
            </dl>
          )}
        </Card>

        {/* Regional */}
        <Card>
          <SectionHeading label="Regional settings" />
          {isError ? (
            <ErrorBanner error={error} />
          ) : !profile ? null : (
            <dl className="divide-y divide-mist">
              <Row label="Country" value={profile.country ?? "—"} />
              <Row label="Timezone" value={profile.timezone ?? "—"} />
              <Row label="Currency" value={profile.currency ?? "—"} />
              <Row label="Language" value={profile.default_language ?? "—"} />
              <Row label="Phone country code" value={profile.phone_country_code ?? "—"} />
            </dl>
          )}
        </Card>

        <p className="text-xs text-slate-neutral">
          Settings are managed by StayKaro platform administrators. For changes
          to your plan, users, or regional configuration, contact support.
        </p>
      </div>
    </div>
  );
}

function SectionHeading({ label }: { label: string }) {
  return (
    <div className="mb-4 text-xs font-medium uppercase tracking-widest text-slate-neutral">
      {label}
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
      <dt className="text-sm text-steel">{label}</dt>
      <dd className="text-sm font-medium text-graphite">{value}</dd>
    </div>
  );
}
