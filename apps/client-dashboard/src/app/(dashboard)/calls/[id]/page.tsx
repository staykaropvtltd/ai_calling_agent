"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useCallQuery } from "../../../../lib/hooks/useCalls";
import { useClientLocale } from "../../../../lib/hooks/useClientLocale";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";

export default function CallDetailPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin", "agent"]}>
      <CallDetail />
    </RoleGuard>
  );
}

function CallDetail() {
  const params = useParams<{ id: string }>();
  const callId = Number(params.id);
  const { formatDateTime } = useClientLocale();

  const { data: call, isLoading, isError, error } = useCallQuery(callId);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }
  if (isError || !call) {
    return <ErrorBanner error={error} />;
  }

  const rows: Array<{ label: string; value: string }> = [
    { label: "Customer", value: call.customer_name ?? "—" },
    { label: "Phone number", value: call.phone_number ?? "—" },
    { label: "Hotel", value: call.hotel_name ?? "—" },
    { label: "Check-in date", value: call.check_in_date ?? "—" },
    { label: "Check-out date", value: call.check_out_date ?? "—" },
    { label: "Created", value: formatDateTime(call.created_at) },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Calls"
        title={`Call #${call.id}`}
        actions={
          <Link href="/calls">
            <Button variant="ghost" size="sm">← Back to calls</Button>
          </Link>
        }
      />

      <div className="max-w-lg">
        <Card>
          <dl className="divide-y divide-mist">
            {rows.map(({ label, value }) => (
              <div key={label} className="flex items-baseline justify-between py-3 first:pt-0 last:pb-0">
                <dt className="text-xs font-medium uppercase tracking-widest text-slate-neutral">
                  {label}
                </dt>
                <dd className="text-sm font-medium text-graphite">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
    </div>
  );
}
