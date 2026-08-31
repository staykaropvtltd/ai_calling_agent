import type { ButtonHTMLAttributes, ReactNode } from "react";
import Link from "next/link";

type Variant = "primary" | "accent" | "ghost" | "outline" | "danger";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

const BASE =
  "inline-flex items-center justify-center gap-2 font-display font-medium tracking-wide transition-colors disabled:opacity-50";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-graphite text-white hover:bg-steel",
  accent: "bg-ember text-white hover:bg-[#e05520]",
  ghost: "bg-transparent text-graphite hover:bg-ash",
  outline: "bg-transparent border border-mist text-graphite hover:border-steel hover:bg-fog",
  danger: "bg-transparent text-red-600 hover:bg-red-50 border border-red-200",
};

const SIZES: Record<Size, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-5 py-2.5 text-sm",
  lg: "px-6 py-3 text-base",
};

export function Button({ variant = "primary", size = "md", className = "", children, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function AnchorButton({
  href,
  variant = "primary",
  size = "md",
  className = "",
  children,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`}>
      {children}
    </Link>
  );
}
