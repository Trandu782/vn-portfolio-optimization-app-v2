"use client";

import { useState } from "react";

import { Card } from "@/components/ui/Card";
import type { SectorCorrelation } from "@/lib/api";
import { correlationColor, orderedHeatmap } from "@/lib/sector-analysis";

const SCALE_SWATCHES = [-1, -0.5, 0, 0.5, 1];

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
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-medium text-fg">Cross-sector correlation</h2>
          <p className="mt-1 text-xs text-fg-muted">
            Pairwise Pearson correlation of the sector indices over{" "}
            <span className="font-mono tabular-nums">{windowLabel}</span>, in a clustered order so
            similar sectors sit together.
          </p>
        </div>
        <div className="text-right text-xs">
          <div className="text-fg-muted">Average correlation</div>
          <div className="mt-0.5 font-mono text-lg font-medium tabular-nums text-fg">
            {averageCorrelation === null ? "n/a" : averageCorrelation.toFixed(2)}
          </div>
          <div className="text-fg-muted">
            Lower means the sectors move more independently.
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table
          className="mx-auto border-separate border-spacing-[2px] text-xs"
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
                <th
                  key={label}
                  scope="col"
                  className="p-1.5 text-xs font-medium text-fg-secondary"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, rowIndex) => (
              <tr key={labels[rowIndex] ?? rowIndex}>
                <th
                  scope="row"
                  className="p-1.5 text-right text-xs font-medium text-fg-secondary whitespace-nowrap"
                >
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
                      className={`h-8 w-12 rounded-sm p-1 text-center font-mono text-xs tabular-nums transition-opacity duration-150 ease-unslop ${
                        inHover ? "ring-2 ring-accent" : ""
                      } ${dimmed ? "opacity-55" : ""}`}
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

      <p className="min-h-[1rem] font-mono text-xs tabular-nums text-fg-secondary" aria-live="polite">
        {hovered ?? "Hover a cell to read the pair."}
      </p>

      <div className="flex items-center gap-1.5 font-mono text-xs text-fg-muted">
        <span aria-hidden="true">-1</span>
        <div className="flex flex-1 gap-1" aria-hidden="true">
          {SCALE_SWATCHES.map((val) => (
            <span
              key={val}
              className="h-2 flex-1 rounded-sm border border-hairline"
              style={{ backgroundColor: correlationColor(val) }}
            />
          ))}
        </div>
        <span aria-hidden="true">+1</span>
        <span className="sr-only">
          Colour scale from minus one (blue) to neutral grey to plus one (red).
        </span>
      </div>
    </Card>
  );
}
