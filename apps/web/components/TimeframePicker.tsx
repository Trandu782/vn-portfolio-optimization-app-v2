"use client";

/**
 * Compact timeframe control shared by the Optimize and Risk pages.
 *
 * Presets count back from the latest available data date; "Custom" reveals two
 * date inputs. The resolved window and an inline validation message are shown so
 * a bad range never reaches the API.
 */

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
        <span className="text-sm font-medium">{label}</span>
        <div
          role="group"
          aria-label="Timeframe preset"
          className="inline-flex flex-wrap overflow-hidden rounded-md border border-gray-300 dark:border-gray-700"
        >
          {TIMEFRAME_PRESETS.map((preset) => {
            const active = selection.preset === preset;
            return (
              <button
                key={preset}
                type="button"
                onClick={() => choosePreset(preset)}
                aria-pressed={active}
                className={
                  active
                    ? "bg-blue-600 px-2.5 py-1 text-xs font-medium text-white"
                    : "px-2.5 py-1 text-xs hover:bg-gray-100 dark:hover:bg-gray-800"
                }
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
            className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400"
          >
            Use same as {copyLabel}
          </button>
        )}
      </div>

      {selection.preset === "Custom" && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1">
            <span className="text-gray-600 dark:text-gray-300">Start</span>
            <input
              type="date"
              value={selection.start}
              max={selection.end || undefined}
              onChange={(event) =>
                onChange({ preset: "Custom", start: event.target.value, end: selection.end })
              }
              className="rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
          <label className="flex items-center gap-1">
            <span className="text-gray-600 dark:text-gray-300">End</span>
            <input
              type="date"
              value={selection.end}
              min={selection.start || undefined}
              max={latestDate ?? undefined}
              onChange={(event) =>
                onChange({ preset: "Custom", start: selection.start, end: event.target.value })
              }
              className="rounded-md border border-gray-300 px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
        </div>
      )}

      <p className="text-xs text-gray-500 dark:text-gray-400">
        {describeWindow(resolved.start, resolved.end)}
      </p>
      {error && <p className="text-xs text-amber-700 dark:text-amber-300">{error}</p>}
    </div>
  );
}
