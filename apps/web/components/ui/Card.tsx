import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  compact?: boolean;
}

export function Card({ children, compact = false, className = "", ...props }: CardProps) {
  return (
    <div
      className={`rounded-xl border border-hairline bg-surface ${compact ? "p-4" : "p-5"} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
