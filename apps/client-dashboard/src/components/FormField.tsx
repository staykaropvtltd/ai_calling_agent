import type { ReactNode } from "react";

interface FormFieldProps {
  label: string;
  htmlFor: string;
  children: ReactNode;
  error?: string;
  hint?: string;
}

export function FormField({ label, htmlFor, children, error, hint }: FormFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium uppercase tracking-widest text-steel">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-slate-neutral">{hint}</p>}
      {error && (
        <p className="text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export const inputClass =
  "rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite placeholder:text-slate-neutral focus:border-steel focus:outline-none focus:ring-1 focus:ring-graphite/20 transition-colors";

export const selectClass =
  "rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-steel focus:outline-none focus:ring-1 focus:ring-graphite/20 transition-colors";

export const buttonClass =
  "inline-flex items-center justify-center font-display font-medium bg-graphite text-white px-5 py-2.5 text-sm tracking-wide transition-colors hover:bg-steel disabled:opacity-40 cursor-pointer";

export const secondaryButtonClass =
  "inline-flex items-center justify-center font-display font-medium border border-mist bg-canvas text-graphite px-5 py-2.5 text-sm tracking-wide transition-colors hover:border-steel hover:bg-fog disabled:opacity-40 cursor-pointer";
