"use client";

import { useParams } from "next/navigation";
import { useCallQuery } from "../../../../lib/hooks/useCalls";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";

export default function CallDetailPage() {
  const params = useParams<{ id: string }>();
  const callId = Number(params.id);

  const { data: call, isLoading, isError, error } = useCallQuery(callId);

  if (isLoading) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }
  if (isError || !call) {
    return <ErrorBanner error={error} />;
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
      <h1 className="mb-6 text-xl font-semibold text-slate-900">Call #{call.id}</h1>
      <Card className="p-6">
        <dl className="flex flex-col gap-3 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between border-b border-slate-100 pb-2">
              <dt className="text-slate-500">{label}</dt>
              <dd className="text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
