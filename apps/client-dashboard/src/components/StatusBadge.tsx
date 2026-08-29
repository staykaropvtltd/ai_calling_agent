const COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  suspended: "bg-amber-100 text-amber-800",
  inactive: "bg-slate-200 text-slate-600",
  super_admin: "bg-purple-100 text-purple-800",
  tenant_admin: "bg-blue-100 text-blue-800",
  agent: "bg-slate-100 text-slate-700",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-slate-400">—</span>;
  const color = COLORS[value] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>
      {value}
    </span>
  );
}
