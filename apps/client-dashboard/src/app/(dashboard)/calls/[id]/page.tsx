"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { RoleGuard } from "../../../../lib/auth/RoleGuard";
import { useCallQuery, useCallTranscript } from "../../../../lib/hooks/useCalls";
import { useClientLocale } from "../../../../lib/hooks/useClientLocale";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";

export default function CallDetailPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin", "agent"]}>
      <CallDetail />
    </RoleGuard>
  );
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function CallDetail() {
  const params = useParams<{ id: string }>();
  const callId = Number(params.id);
  const { formatDateTime } = useClientLocale();

  const { data: call, isLoading, isError, error } = useCallQuery(callId);
  const { data: transcript, isLoading: transcriptLoading } = useCallTranscript(callId);

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

  const basicRows: Array<{ label: string; value: React.ReactNode }> = [
    { label: "Customer", value: call.customer_name ?? "—" },
    { label: "Phone number", value: call.phone_number ?? "—" },
    { label: "Hotel / Property", value: call.hotel_name ?? "—" },
    { label: "Check-in date", value: call.check_in_date ?? "—" },
    { label: "Check-out date", value: call.check_out_date ?? "—" },
    { label: "Created", value: formatDateTime(call.created_at) },
  ];

  const callRows: Array<{ label: string; value: React.ReactNode }> = [
    { label: "Status", value: <StatusBadge value={call.status ?? "pending"} /> },
    { label: "Type", value: call.call_type ?? "outbound" },
    {
      label: "Connection",
      value: call.connection_status
        ? call.connection_status.replace(/_/g, " ")
        : "—",
    },
    { label: "Duration", value: formatDuration(call.duration_seconds) },
    { label: "Outcome", value: call.outcome ? call.outcome.replace(/_/g, " ") : "—" },
    {
      label: "Failure reason",
      value: call.failure_reason ? call.failure_reason.replace(/_/g, " ") : "—",
    },
    {
      label: "Simulation",
      value: call.is_simulation ? "Yes — dev/test call" : "No — real call",
    },
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

      {call.is_simulation && (
        <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          This is a simulation call (dev/test). It does not represent a real telephony session and
          will not appear in production analytics.
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Guest / booking info */}
        <Card>
          <div className="mb-4 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            Booking details
          </div>
          <dl className="divide-y divide-mist">
            {basicRows.map(({ label, value }) => (
              <div
                key={label}
                className="flex items-baseline justify-between py-3 first:pt-0 last:pb-0"
              >
                <dt className="text-xs font-medium uppercase tracking-widest text-slate-neutral">
                  {label}
                </dt>
                <dd className="text-sm font-medium text-graphite">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>

        {/* Call result */}
        <Card>
          <div className="mb-4 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            Call result
          </div>
          <dl className="divide-y divide-mist">
            {callRows.map(({ label, value }) => (
              <div
                key={label}
                className="flex items-baseline justify-between py-3 first:pt-0 last:pb-0"
              >
                <dt className="text-xs font-medium uppercase tracking-widest text-slate-neutral">
                  {label}
                </dt>
                <dd className="text-sm font-medium text-graphite">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      {/* Recording */}
      <div className="mt-5">
        <Card>
          <div className="mb-3 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            Recording
          </div>
          <p className="text-sm text-slate-neutral">No recording available.</p>
        </Card>
      </div>

      {/* Transcript */}
      <div className="mt-5">
        <Card padding={false}>
          <div className="border-b border-mist px-6 py-4">
            <div className="text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
              Conversation transcript
            </div>
          </div>
          {transcriptLoading ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : !transcript || transcript.length === 0 ? (
            <p className="px-6 py-8 text-sm text-slate-neutral">
              No transcript available.{" "}
              {call.status === "pending" || call.status === "queued"
                ? "The call has not started yet."
                : call.status === "dialing" || call.status === "ringing"
                  ? "The call is in progress — transcript will appear when complete."
                  : "The telephony provider may not have returned a transcript for this call."}
            </p>
          ) : (
            <ul className="divide-y divide-mist/60">
              {transcript.map((turn) => (
                <li
                  key={turn.turn_id}
                  className={`px-6 py-4 ${turn.speaker === "agent" ? "bg-fog/40" : "bg-canvas"}`}
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span
                      className={`text-[10px] font-bold uppercase tracking-widest ${
                        turn.speaker === "agent" ? "text-ember" : "text-steel"
                      }`}
                    >
                      {turn.speaker === "agent" ? "AI Agent" : "Guest"}
                    </span>
                    <span className="text-[10px] text-slate-neutral">
                      {formatDateTime(turn.started_at)}
                    </span>
                  </div>
                  <p className="text-sm text-graphite leading-relaxed">{turn.text}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
