import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "accent" | "positive" | "negative" | "warn";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-hairline bg-raised text-fg-secondary",
  accent: "border-accent/25 bg-accent-subtle text-accent-ink",
  positive: "border-positive/25 bg-positive-subtle text-positive",
  negative: "border-negative/25 bg-negative-subtle text-negative",
  warn: "border-warn-border bg-warn-subtle text-warn",
};

export function Badge({
  tone = "neutral",
  className = "",
  children,
}: {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs tabular-nums ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
