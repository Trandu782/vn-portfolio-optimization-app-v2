"use client";

/** A small "how to read this" marker that shows `text` on hover/focus. */
export function InfoTip({ text }: { text: string }) {
  return (
    <span
      title={text}
      aria-label={text}
      role="img"
      className="ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-gray-300 text-[10px] leading-none text-gray-500 dark:border-gray-600 dark:text-gray-400"
    >
      ?
    </span>
  );
}
