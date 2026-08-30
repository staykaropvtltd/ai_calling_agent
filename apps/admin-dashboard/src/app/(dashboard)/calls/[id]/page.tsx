"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallQuery } from "../../../../lib/hooks/useCalls";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";

export default function CallDetailPage() {
  const params = useParams<{ id: string }>();
  const callId = Number(params.id);

  const { data: call, isLoading, isError, error } = useCallQuery(callId);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }
  if (isError || !call) {
    return (
      <div className="max-w-lg">
        <ErrorBanner error={error} />
      </div>
    );
  }

  const rows: Array<[string, string]> = [
    ["Customer", call.customer_name ?? "—"],
    ["Phone", call.phone_number ?? "—"],
    ["Hotel", call.hotel_name ?? "—"],
    ["Check-in", call.check_in_date ?? "—"],
    ["Check-out", call.check_out_date ?? "—"],
    ["Created", call.created_at ? new Date(call.created_at).toLocaleString() : "—"],
  ];

  return (
    <div className="max-w-lg">
      <PageHeader
        eyebrow="Calls"
        title={`Call #${call.id}`}
        actions={
          <Link href="/calls">
            <Button variant="ghost" size="sm">← All calls</Button>
          </Link>
        }
      />

      <Card>
        <dl className="divide-y divide-mist">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between py-3">
              <dt className="text-xs font-medium uppercase tracking-widest text-slate-neutral">
                {label}
              </dt>
              <dd className="text-sm text-graphite">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
