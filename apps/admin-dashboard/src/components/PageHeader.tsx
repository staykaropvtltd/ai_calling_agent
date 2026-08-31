import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  eyebrow?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, description, eyebrow, actions }: PageHeaderProps) {
  return (
    <div className="mb-8 flex items-start justify-between gap-6">
      <div>
        {eyebrow && (
          <p className="mb-1 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            {eyebrow}
          </p>
        )}
        <h1 className="font-display text-2xl font-semibold text-graphite">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-slate-neutral">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
