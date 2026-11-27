"use client";

import { HelpCircleIcon } from "@/components/ui/Icons";

/** A small "how to read this" marker that shows `text` on hover/focus. */
export function InfoTip({ text }: { text: string }) {
  return (
    <span
      title={text}
      aria-label={text}
      role="img"
      tabIndex={0}
      className="ml-1 inline-flex cursor-help items-center align-middle text-fg-muted transition-colors duration-150 ease-unslop hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm"
    >
      <HelpCircleIcon size={14} />
    </span>
  );
}
