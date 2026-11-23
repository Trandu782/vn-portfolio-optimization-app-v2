"use client";

/**
 * Cross-Sector Correlation heatmap (docs/V2_SPEC.md section 3.2).
 *
 * N x N Pearson correlation on the clustered display order, a diverging -1..+1 scale
 * with an opaque neutral grey at 0 (so neutral cells read on a dark background), a hover
 * tooltip with the exact value and the window label, and the average pairwise correlation
 * as the diversification indicator.
 */

import { useState } from "react";

import type { SectorCorrelation } from "@/lib/api";
import { correlationColor, orderedHeatmap } from "@/lib/sector-analysis";

export function SectorCorrelationHeatmap({
  correlation,
  windowLabel,
  averageCorrelation,
}: {
  correlation: SectorCorrelation;
  windowLabel: string;
  averageCorrelation: number | null;
}) {
  const { labels, matrix } = orderedHeatmap(correlation);
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);
  const hovered =
    hover === null
      ? null
      : `${labels[hover.row]} vs ${labels[hover.col]}: ${(matrix[hover.row]?.[hover.col] ?? 0).toFixed(2)} (${windowLabel})`;

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Cross-sector correlation</h2>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            Pairwise Pearson correlation of the sector indices over {windowLabel}, in a
            clustered order so similar sectors sit together. Red is positive, blue negative,
            and grey is no relationship.
          </p>
        </div>
        <div className="text-right text-xs">
          <div className="text-gray-500 dark:text-gray-400">Average correlation</div>
          <div className="text-lg font-semibold tabular-nums">
            {averageCorrelation === null ? "n/a" : averageCorrelation.toFixed(2)}
          </div>
          <div className="text-gray-500 dark:text-gray-400">
            Lower means the sectors move more independently (more diversification).
          </div>
        </div>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table
          className="border-collapse text-[10px]"
          aria-label="Pairwise correlation of the sector indices"
          onMouseLeave={() => setHover(null)}
        >
          <caption className="sr-only">
            Correlation of each pair of sectors in clustered order; hover a cell to read the pair.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="p-1" />
              {labels.map((label) => (
                <th key={label} scope="col" className="p-1 font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, rowIndex) => (
              <tr key={labels[rowIndex] ?? rowIndex}>
                <th scope="row" className="p-1 text-right font-medium">
                  {labels[rowIndex]}
                </th>
                {row.map((value, columnIndex) => {
                  const inHover =
                    hover !== null && (hover.row === rowIndex || hover.col === columnIndex);
                  const dimmed = hover !== null && !inHover;
                  return (
                    <td
                      key={`${rowIndex}-${columnIndex}`}
                      onMouseEnter={() => setHover({ row: rowIndex, col: columnIndex })}
                      onFocus={() => setHover({ row: rowIndex, col: columnIndex })}
                      tabIndex={0}
                      title={`${labels[rowIndex]} vs ${labels[columnIndex]}: ${value.toFixed(2)} (${windowLabel})`}
                      aria-label={`${labels[rowIndex]} vs ${labels[columnIndex]}: ${value.toFixed(2)}`}
                      className={`h-7 w-10 p-1 text-center ${
                        inHover ? "ring-2 ring-blue-500" : ""
                      } ${dimmed ? "opacity-60" : ""}`}
                      style={{
                        backgroundColor: correlationColor(value),
                        color: Math.abs(value) > 0.55 ? "#ffffff" : undefined,
                      }}
                    >
                      {value.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2 min-h-[1rem] text-xs text-gray-600 dark:text-gray-300" aria-live="polite">
        {hovered ?? "Hover a cell to read the pair."}
      </p>

      <div className="mt-2 flex items-center gap-2 text-[10px] text-gray-500 dark:text-gray-400">
        <span aria-hidden>-1</span>
        <span
          className="h-2 flex-1 rounded-full"
          style={{
            backgroundImage:
              "linear-gradient(to right, rgb(37,99,235), rgb(107,114,128), rgb(220,38,38))",
            border: "1px solid rgba(107,114,128,0.3)",
          }}
          aria-hidden
        />
        <span aria-hidden>+1</span>
        <span className="sr-only">Colour scale from minus one (blue) to neutral grey to plus one (red).</span>
      </div>
    </div>
  );
}

