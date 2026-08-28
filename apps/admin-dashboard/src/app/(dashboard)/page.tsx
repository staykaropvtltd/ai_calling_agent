"use client";

import { useAuth } from "../../lib/auth/useAuth";
import { useTenantsQuery } from "../../lib/hooks/useTenants";
import { useCallsQuery } from "../../lib/hooks/useCalls";
import { useUsersQuery } from "../../lib/hooks/useUsers";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";

export default function OverviewPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";

  const tenants = useTenantsQuery({ page: 1, per_page: 1 });
  const users = useUsersQuery({ page: 1, per_page: 1 });
  const calls = useCallsQuery({ page: 1, per_page: 1 });

  return (
    <div>
      <h1 className="mb-6 text-xl font-semibold text-slate-900">Overview</h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {isSuperAdmin ? (
          <StatCard label="Tenants" query={tenants} />
        ) : null}
        <StatCard label="Users" query={users} />
        <StatCard label="Calls" query={calls} />
      </div>
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
