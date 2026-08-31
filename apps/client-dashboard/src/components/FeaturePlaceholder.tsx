import type { ReactNode } from "react";

interface FeaturePlaceholderProps {
  title: string;
  description: string;
  icon?: string;
  eta?: string;
  actions?: ReactNode;
}

export function FeaturePlaceholder({
  title,
  description,
  icon = "◦",
  eta,
  actions,
}: FeaturePlaceholderProps) {
  return (
    <div className="flex min-h-[420px] flex-col items-center justify-center px-6 py-16 text-center">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl border border-mist bg-canvas text-3xl text-slate-neutral">
        {icon}
      </div>
      <h1 className="mb-2 font-display text-xl font-semibold tracking-display text-graphite">
        {title}
      </h1>
      <p className="mb-6 max-w-sm text-sm leading-relaxed text-slate-neutral">
        {description}
      </p>
      {eta && (
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-mist bg-canvas px-4 py-1.5 text-xs font-medium text-steel">
          <span className="h-1.5 w-1.5 rounded-full bg-ember" />
          {eta}
        </div>
      )}
      {actions && <div className="flex gap-3">{actions}</div>}
    </div>
  );
}
