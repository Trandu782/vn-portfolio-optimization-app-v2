/**
 * Inline disclaimer shown on every page that presents results.
 *
 * The footer also carries it globally; repeating it next to the numbers keeps the
 * "decision support, not financial advice" message visible where it matters.
 * `verb` keeps the sentence grammatical for singular subjects ("This universe").
 */
export function Disclaimer({
  context,
  verb = "are",
}: {
  context?: string;
  verb?: "is" | "are";
}) {
  const subject = context ?? "These results";
  return (
    <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
      {subject} {verb} decision support only, not financial advice. Past performance and simulated
      scenarios do not guarantee future results; verify prices and rules with your broker before
      trading.
    </p>
  );
}
