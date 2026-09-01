"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useCallsQuery } from "../../../lib/hooks/useCalls";
import { useClientLocale } from "../../../lib/hooks/useClientLocale";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { PageHeader } from "../../../components/PageHeader";
import { Button } from "../../../components/Button";
import { StatusBadge } from "../../../components/StatusBadge";
import type { CallLogEntry } from "../../../lib/types/call";

export default function CallsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin", "agent"]}>
      <CallsList />
    </RoleGuard>
  );
}

function CallsList() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const { formatDateTime } = useClientLocale();

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
    setDebouncedSearch(value);
  }

  const { data, isLoading, isError, error } = useCallsQuery({
    page,
    per_page: 20,
    search: debouncedSearch || undefined,
  });

  const columns: Column<CallLogEntry>[] = [
    {
      key: "customer_name",
      header: "Customer",
      render: (c) => (
        <span className="font-medium text-graphite">{c.customer_name ?? "—"}</span>
      ),
    },
    { key: "phone_number", header: "Phone", render: (c) => c.phone_number ?? "—" },
    { key: "hotel_name", header: "Hotel / Property", render: (c) => c.hotel_name ?? "—" },
    {
      key: "status",
      header: "Status",
      render: (c) => <StatusBadge value={c.status ?? "pending"} />,
    },
    {
      key: "duration_seconds",
      header: "Duration",
      render: (c) =>
        c.duration_seconds != null
          ? `${Math.floor(c.duration_seconds / 60)}:${String(c.duration_seconds % 60).padStart(2, "0")}`
          : "—",
    },
    {
      key: "created_at",
      header: "Created",
      render: (c) => (
        <span className="text-slate-neutral">{formatDateTime(c.created_at)}</span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Calls"
        title="Call Log"
        description="All outbound AI calls placed through StayKaro."
        actions={
          <Link href="/calls/new">
            <Button variant="accent">New Call</Button>
          </Link>
        }
      />

      {/* Search */}
      <div className="mb-4">
        <input
          type="search"
          placeholder="Search by customer name or phone…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="w-full max-w-xs rounded-xl border border-mist bg-canvas px-4 py-2 text-sm placeholder:text-slate-neutral focus:border-steel focus:outline-none"
          aria-label="Search calls"
        />
      </div>

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
              rowKey={(c) => String(c.id)}
              onRowClick={(c) => router.push(`/calls/${c.id}`)}
              emptyMessage={
                debouncedSearch ? "No calls match your search." : "No calls yet."
              }
            />
            <Pagination
              page={page}
              totalPages={data?.total_pages ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </div>
  );
}
