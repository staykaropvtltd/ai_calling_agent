const COLORS: Record<string, string> = {
  active: "border-emerald-200 bg-emerald-50 text-emerald-800",
  suspended: "border-amber-200 bg-amber-50 text-amber-800",
  inactive: "border-mist bg-ash text-slate-neutral",
  coming_soon: "border-mist bg-fog text-slate-neutral",
  available: "border-mist bg-canvas text-steel",
  super_admin: "border-graphite bg-graphite text-white",
  tenant_admin: "border-steel bg-steel text-white",
  agent: "border-mist bg-ash text-steel",
  starter: "border-mist bg-fog text-steel",
  pro: "border-brass bg-ivory text-brass",
  enterprise: "border-graphite bg-graphite text-white",
  active_exotel: "border-emerald-200 bg-emerald-50 text-emerald-800",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-slate-neutral">—</span>;
  const displayValue = value.replace(/_/g, " ");
  const color = COLORS[value] ?? "border-mist bg-fog text-steel";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-display font-medium ${color}`}
    >
      {displayValue}
    </span>
  );
}
