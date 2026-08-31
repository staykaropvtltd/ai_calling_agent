"use client";

import { useState } from "react";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { usePhoneNumbersQuery } from "../../../lib/hooks/usePhoneNumbers";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { StatusBadge } from "../../../components/StatusBadge";
import { PageHeader } from "../../../components/PageHeader";
import type { PhoneNumber } from "../../../lib/types/phoneNumber";

export default function PhoneNumbersPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <PhoneNumbersList />
    </RoleGuard>
  );
}

function PhoneNumbersList() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, error } = usePhoneNumbersQuery({ page, per_page: 20 });

  const columns: Column<PhoneNumber>[] = [
    {
      key: "number",
      header: "Phone number",
      render: (n) => (
        <span className="font-mono font-medium text-graphite">{n.number}</span>
      ),
    },
    {
      key: "provider",
      header: "Provider",
      render: (n) => <StatusBadge value={n.provider} />,
    },
    {
      key: "agent_id",
      header: "Agent ID",
      render: (n) => <span className="text-slate-neutral">{n.agent_id ?? "—"}</span>,
    },
    {
      key: "created_at",
      header: "Registered",
      render: (n) =>
        n.created_at ? new Date(n.created_at).toLocaleDateString() : "—",
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Management"
        title="Phone Numbers"
        description="Numbers assigned to your hotel's AI agent."
      />

      <Card padding={false}>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : isError ? (
          <div className="p-6">
            <ErrorBanner error={error} />
          </div>
        ) : (
          <>
            <Table
              columns={columns}
              rows={data?.data ?? []}
              rowKey={(n) => n.number}
              emptyMessage="No phone numbers assigned. Contact StayKaro support to provision a number."
            />
            <Pagination page={page} totalPages={data?.total_pages ?? 0} onPageChange={setPage} />
          </>
        )}
      </Card>

      <p className="mt-4 text-xs text-slate-neutral">
        Phone numbers are provisioned by StayKaro administrators. Contact{" "}
        <a href="mailto:support@staykaro.com" className="text-graphite underline">
          support@staykaro.com
        </a>{" "}
        to request a new number or change routing.
      </p>
    </div>
  );
}
