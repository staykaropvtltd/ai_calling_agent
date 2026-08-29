"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useCallsQuery } from "../../../lib/hooks/useCalls";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import type { CallLogEntry } from "../../../lib/types/call";

export default function CallsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <CallsList />
    </RoleGuard>
  );
}

function CallsList() {
  const router = useRouter();
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, error } = useCallsQuery({ page, per_page: 20 });

  const columns: Column<CallLogEntry>[] = [
    { key: "customer_name", header: "Customer", render: (c) => c.customer_name ?? "—" },
    { key: "phone_number", header: "Phone", render: (c) => c.phone_number ?? "—" },
    { key: "hotel_name", header: "Hotel", render: (c) => c.hotel_name ?? "—" },
    { key: "check_in_date", header: "Check-in", render: (c) => c.check_in_date ?? "—" },
    { key: "check_out_date", header: "Check-out", render: (c) => c.check_out_date ?? "—" },
    {
      key: "created_at",
      header: "Created",
      render: (c) => (c.created_at ? new Date(c.created_at).toLocaleString() : "—"),
    },
  ];

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold text-slate-900">Calls</h1>

      <Card>
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : isError ? (
          <div className="p-4">
            <ErrorBanner error={error} />
          </div>
        ) : (
          <>
            <Table
              columns={columns}
              rows={data?.data ?? []}
              rowKey={(c) => String(c.id)}
              onRowClick={(c) => router.push(`/calls/${c.id}`)}
              emptyMessage="No calls yet."
            />
            <Pagination page={page} totalPages={data?.total_pages ?? 0} onPageChange={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
