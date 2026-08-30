import type { ReactNode } from "react";

interface FormFieldProps {
  label: string;
  htmlFor: string;
  children: ReactNode;
  error?: string;
}

export function FormField({ label, htmlFor, children, error }: FormFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={htmlFor}
        className="text-xs font-medium uppercase tracking-widest text-steel"
      >
        {label}
      </label>
      {children}
      {error && (
        <p className="text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export const inputClass =
  "rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-graphite focus:outline-none placeholder:text-slate-neutral";

export const buttonClass =
  "inline-flex items-center justify-center gap-2 bg-graphite px-5 py-2.5 font-display text-sm font-medium text-white transition-colors hover:bg-steel disabled:opacity-50";

export const secondaryButtonClass =
  "inline-flex items-center justify-center gap-2 border border-mist bg-canvas px-5 py-2.5 font-display text-sm font-medium text-graphite transition-colors hover:border-steel hover:bg-fog";
