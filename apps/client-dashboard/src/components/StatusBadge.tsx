const MAP: Record<string, { bg: string; text: string; label?: string }> = {
  active: { bg: "bg-emerald-50 border border-emerald-200", text: "text-emerald-700", label: "Active" },
  inactive: { bg: "bg-fog border border-mist", text: "text-slate-neutral", label: "Inactive" },
  suspended: { bg: "bg-amber-50 border border-amber-200", text: "text-amber-700", label: "Suspended" },
  pending: { bg: "bg-blue-50 border border-blue-200", text: "text-blue-700", label: "Pending" },
  failed: { bg: "bg-red-50 border border-red-200", text: "text-red-700", label: "Failed" },
  completed: { bg: "bg-emerald-50 border border-emerald-200", text: "text-emerald-700", label: "Completed" },
  processing: { bg: "bg-blue-50 border border-blue-200", text: "text-blue-700", label: "Processing" },
  queued: { bg: "bg-fog border border-mist", text: "text-steel", label: "Queued" },
  retrying: { bg: "bg-amber-50 border border-amber-200", text: "text-amber-700", label: "Retrying" },
  super_admin: { bg: "bg-graphite", text: "text-white", label: "Super Admin" },
  tenant_admin: { bg: "bg-steel", text: "text-white", label: "Admin" },
  agent: { bg: "bg-fog border border-mist", text: "text-steel", label: "Agent" },
  starter: { bg: "bg-fog border border-mist", text: "text-steel", label: "Starter" },
  pro: { bg: "bg-ivory border border-[#d9d4cb]", text: "text-brass", label: "Pro" },
  enterprise: { bg: "bg-graphite", text: "text-white", label: "Enterprise" },
  coming_soon: { bg: "bg-fog border border-mist", text: "text-slate-neutral", label: "Coming soon" },
  available: { bg: "bg-ivory border border-[#d9d4cb]", text: "text-brass", label: "Available" },
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  const config = MAP[value] ?? {
    bg: "bg-fog border border-mist",
    text: "text-steel",
    label: value,
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-display font-medium ${config.bg} ${config.text}`}
    >
      {config.label ?? value}
    </span>
  );
}
