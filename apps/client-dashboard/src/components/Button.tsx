import type { ButtonHTMLAttributes, ReactNode, AnchorHTMLAttributes } from "react";

type Variant = "primary" | "accent" | "ghost" | "outline" | "danger";
type Size = "xs" | "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children?: ReactNode;
}

const BASE =
  "inline-flex items-center justify-center gap-2 font-display font-medium tracking-wide transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember focus-visible:ring-offset-1 cursor-pointer select-none";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-graphite text-white hover:bg-steel",
  accent: "bg-ember text-white hover:bg-[#e05520]",
  ghost: "bg-transparent text-graphite hover:bg-ash",
  outline: "bg-transparent border border-mist text-graphite hover:border-steel hover:bg-fog",
  danger: "bg-transparent text-red-600 hover:bg-red-50 border border-red-200",
};

const SIZES: Record<Size, string> = {
  xs: "px-2.5 py-1 text-[11px]",
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
  lg: "px-6 py-2.5 text-sm",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    >
      {children}
    </button>
  );
}

interface AnchorButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: Variant;
  size?: Size;
  children?: ReactNode;
}

export function AnchorButton({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: AnchorButtonProps) {
  return (
    <a
      {...props}
      className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    >
      {children}
    </a>
  );
}
