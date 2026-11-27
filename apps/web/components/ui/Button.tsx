import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-cta text-cta-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] hover:bg-cta-hover disabled:opacity-50",
  secondary:
    "border border-strong bg-raised text-fg hover:bg-surface disabled:opacity-50",
  ghost:
    "text-fg-secondary hover:bg-raised hover:text-fg disabled:opacity-50",
  danger:
    "border border-negative/30 bg-negative-subtle text-negative hover:bg-negative/15 disabled:opacity-50",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-10 md:h-8 px-3 text-xs",
  md: "h-11 md:h-9 px-4 text-sm",
};

export function buttonClass({
  variant = "secondary",
  size = "md",
  className = "",
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
} = {}) {
  return [
    "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium whitespace-nowrap",
    "active:scale-[0.98] transition-[background-color,border-color,color,transform] duration-150 ease-unslop",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page",
    "disabled:cursor-not-allowed disabled:active:scale-100",
    VARIANT_CLASSES[variant],
    SIZE_CLASSES[size],
    className,
  ]
    .filter(Boolean)
    .join(" ");
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClass({ variant, size, className })}
      {...props}
    />
  );
}
