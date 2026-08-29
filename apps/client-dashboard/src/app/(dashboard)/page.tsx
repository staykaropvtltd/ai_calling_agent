"use client";

import Link from "next/link";
import { useAuth } from "../../lib/auth/useAuth";
import { useCallsQuery } from "../../lib/hooks/useCalls";
import { useUsersQuery } from "../../lib/hooks/useUsers";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { buttonClass } from "../../components/FormField";

export default function OverviewPage() {
  const { user } = useAuth();
  const isTenantAdmin = user?.role === "tenant_admin";

  // /admin/users and /admin/calls 403 for "agent" tokens (see the layout's
  // nav comment) — only fetch stats when they'd actually succeed.
  const users = useUsersQuery({ page: 1, per_page: 1 }, { enabled: isTenantAdmin });
  const calls = useCallsQuery({ page: 1, per_page: 1 }, { enabled: isTenantAdmin });

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Overview</h1>
        <Link href="/calls/new" className={buttonClass}>
          New call
        </Link>
      </div>

      {isTenantAdmin ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <StatCard label="Users" query={users} />
          <StatCard label="Calls" query={calls} />
        </div>
      ) : (
        <Card className="p-6">
          <p className="text-sm text-slate-600">
            Welcome, {user?.full_name}. Use <span className="font-medium">New call</span> to place an
            outbound call.
          </p>
        </Card>
      )}
    </div>
  );
}

function StatCard({
  label,
  query,
}: {
  label: string;
  query: { isLoading: boolean; isError: boolean; data?: { total: number } };
}) {
  return (
    <Card className="p-5">
      <div className="text-sm font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">
        {query.isLoading ? <Spinner /> : query.isError ? "—" : query.data?.total}
      </div>
    </Card>
  );
}
