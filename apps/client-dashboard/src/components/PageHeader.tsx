import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  eyebrow?: string;
}

export function PageHeader({ title, description, actions, eyebrow }: PageHeaderProps) {
  return (
    <div className="mb-8 flex items-start justify-between gap-6">
      <div>
        {eyebrow && (
          <div className="mb-1 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            {eyebrow}
          </div>
        )}
        <h1 className="font-display text-2xl font-semibold tracking-display text-graphite">
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 text-sm text-slate-neutral">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-3">{actions}</div>
      )}
    </div>
  );
}
