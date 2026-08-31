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
  icon = "◎",
  eta,
  actions,
}: FeaturePlaceholderProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-mist bg-canvas px-8 py-20 text-center">
      <span className="mb-4 text-4xl text-slate-neutral" aria-hidden>
        {icon}
      </span>
      <h2 className="mb-2 font-display text-xl font-semibold text-graphite">{title}</h2>
      <p className="max-w-sm text-sm text-steel">{description}</p>
      {eta && (
        <span className="mt-5 inline-flex items-center gap-1.5 rounded-full border border-mist bg-fog px-3 py-1 text-xs text-slate-neutral">
          <span className="h-1.5 w-1.5 rounded-full bg-ember" />
          {eta}
        </span>
      )}
      {actions && <div className="mt-6 flex gap-3">{actions}</div>}
    </div>
  );
}
