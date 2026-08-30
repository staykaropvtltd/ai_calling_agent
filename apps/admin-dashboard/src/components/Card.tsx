import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: boolean;
  tint?: "none" | "ivory" | "ash";
}

export function Card({ children, className = "", padding = true, tint = "none" }: CardProps) {
  const tintClass =
    tint === "ivory" ? "bg-ivory" : tint === "ash" ? "bg-ash" : "bg-canvas";
  return (
    <div
      className={`rounded-2xl border border-mist ${tintClass} ${padding ? "p-6" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: ReactNode;
  sub?: string;
  accent?: boolean;
}

export function StatCard({ label, value, sub, accent = false }: StatCardProps) {
  return (
    <Card tint={accent ? "none" : "none"} className={accent ? "border-graphite" : ""}>
      <div className="text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
        {label}
      </div>
      <div className={`mt-2 font-display text-3xl font-semibold ${accent ? "text-ember" : "text-graphite"}`}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-neutral">{sub}</div>}
    </Card>
  );
}
