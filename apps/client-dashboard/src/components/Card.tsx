import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  /** Default true — adds p-6. Pass false for full-bleed content (table cards). */
  padding?: boolean;
  /** Ivory tinted surface for featured/highlighted cards */
  tint?: "ivory" | "ash" | "none";
}

export function Card({
  children,
  className = "",
  padding = true,
  tint = "none",
}: CardProps) {
  const tintClass =
    tint === "ivory"
      ? "bg-ivory border-[#d9d4cb]"
      : tint === "ash"
        ? "bg-ash border-mist"
        : "bg-canvas border-mist";

  return (
    <div
      className={`rounded-2xl border ${tintClass} ${padding ? "p-6" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

/** Compact card used for stat tiles */
export function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number | ReactNode;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <Card className={accent ? "border-ember/20 bg-ember/5" : ""}>
      <div className="text-xs font-medium uppercase tracking-wider text-slate-neutral">
        {label}
      </div>
      <div
        className={`mt-2 font-display text-3xl font-semibold tracking-display ${
          accent ? "text-ember" : "text-graphite"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-neutral">{sub}</div>}
    </Card>
  );
}
