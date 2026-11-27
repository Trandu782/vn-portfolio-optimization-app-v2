"use client";

/**
 * Compact timeframe control shared by the Optimize and Risk pages.
 *
 * Presets count back from the latest available data date; "Custom" reveals two
 * date inputs. The resolved window and an inline validation message are shown so
 * a bad range never reaches the API.
 */

import { inputCompactClass } from "@/components/ui/Field";
import {
  TIMEFRAME_PRESETS,
  describeWindow,
  resolveTimeframe,
  todayIso,
  validateWindow,
  type TimeframePreset,
  type TimeframeSelection,
} from "@/lib/timeframe";

export interface TimeframePickerProps {
  selection: TimeframeSelection;
  /** Latest available data date (ISO), or null while it is being loaded. */
  latestDate: string | null;
  onChange: (selection: TimeframeSelection) => void;
  /** Label of the other tab, for the "Use same as ..." link. */
  copyLabel?: string;
  onCopyOther?: () => void;
  label?: string;
}

export function TimeframePicker({
  selection,
  latestDate,
  onChange,
  copyLabel,
  onCopyOther,
  label = "Timeframe",
}: TimeframePickerProps) {
  const resolved = resolveTimeframe(selection, latestDate ?? todayIso());
  const error = validateWindow(resolved.start, resolved.end, latestDate);

  function choosePreset(preset: TimeframePreset) {
    if (preset === "Custom") {
      // Seed the inputs with the current window so they never open blank.
      onChange({ preset: "Custom", start: resolved.start, end: resolved.end });
      return;
    }
    onChange({ preset, start: "", end: "" });
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-fg">{label}</span>
        <div
          role="group"
          aria-label="Timeframe preset"
          className="inline-flex flex-wrap overflow-hidden rounded-lg border border-strong bg-raised"
        >
          {TIMEFRAME_PRESETS.map((preset) => {
            const active = selection.preset === preset;
            return (
              <button
                key={preset}
                type="button"
                onClick={() => choosePreset(preset)}
                aria-pressed={active}
                className={`min-h-[40px] md:min-h-0 px-3 py-1.5 text-xs font-medium transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent ${
                  active
                    ? "bg-accent text-white"
                    : "text-fg-secondary hover:bg-surface hover:text-fg"
                }`}
              >
                {preset}
              </button>
            );
          })}
        </div>
        {copyLabel && onCopyOther && (
          <button
            type="button"
            onClick={onCopyOther}
            className="text-xs text-accent-ink transition-colors duration-150 ease-unslop hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm"
          >
            Use same as {copyLabel}
          </button>
        )}
      </div>

      {selection.preset === "Custom" && (
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-2">
            <span className="text-fg-secondary">Start</span>
            <input
              type="date"
              value={selection.start}
              max={selection.end || undefined}
              onChange={(event) =>
                onChange({ preset: "Custom", start: event.target.value, end: selection.end })
              }
              className={`${inputCompactClass} font-mono tabular-nums`}
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="text-fg-secondary">End</span>
            <input
              type="date"
              value={selection.end}
              min={selection.start || undefined}
              max={latestDate ?? undefined}
              onChange={(event) =>
                onChange({ preset: "Custom", start: selection.start, end: event.target.value })
              }
              className={`${inputCompactClass} font-mono tabular-nums`}
            />
          </label>
        </div>
      )}

      <p className="font-mono text-xs tabular-nums text-fg-muted">
        {describeWindow(resolved.start, resolved.end)}
      </p>
      {error && <p className="text-xs text-warn">{error}</p>}
    </div>
  );
}
