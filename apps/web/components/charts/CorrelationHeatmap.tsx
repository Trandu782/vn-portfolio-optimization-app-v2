"use client";

import { useState } from "react";

import { Card } from "@/components/ui/Card";
import type { CorrelationMatrixMetric } from "@/lib/api";

function correlationColor(value: number): string {
  const clamped = Math.max(-1, Math.min(1, value));
  if (clamped >= 0) {
    return `rgba(229, 72, 77, ${(clamped * 0.68).toFixed(3)})`;
  }
  return `rgba(59, 130, 246, ${(-clamped * 0.68).toFixed(3)})`;
}

const SCALE_SWATCHES = [-1, -0.5, 0, 0.5, 1];

export function CorrelationHeatmap({ metric }: { metric: CorrelationMatrixMetric }) {
  const symbols = metric.symbols;
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);
  const hovered =
    hover === null
      ? null
      : `${symbols[hover.row]} vs ${symbols[hover.col]}: ${(metric.matrix[hover.row]?.[hover.col] ?? 0).toFixed(2)}`;

  return (
    <Card className="space-y-3">
      <div>
        <h3 className="text-sm font-medium text-fg">Correlation heatmap</h3>
        <p className="mt-1 text-xs text-fg-muted">
          Pairwise correlation of the analysed symbols. Red is positive, blue is negative.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table
          className="mx-auto border-separate border-spacing-[2px] text-xs"
          onMouseLeave={() => setHover(null)}
          aria-label="Pairwise correlation matrix of the analysed symbols"
        >
          <caption className="sr-only">
            Correlation of each pair of stocks; hover a cell to read the pair.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="p-1" />
              {symbols.map((symbol) => (
                <th
                  key={symbol}
                  scope="col"
                  className="p-1.5 font-mono text-xs font-medium text-fg-secondary"
                >
                  {symbol}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metric.matrix.map((row, rowIndex) => (
              <tr key={symbols[rowIndex] ?? rowIndex}>
                <th
                  scope="row"
                  className="p-1.5 text-right font-mono text-xs font-medium text-fg-secondary"
                >
                  {symbols[rowIndex]}
                </th>
                {row.map((value, columnIndex) => {
                  const inHover =
                    hover !== null &&
                    (hover.row === rowIndex || hover.col === columnIndex);
                  const dimmed = hover !== null && !inHover;
                  return (
                    <td
                      key={`${rowIndex}-${columnIndex}`}
                      onMouseEnter={() => setHover({ row: rowIndex, col: columnIndex })}
                      onFocus={() => setHover({ row: rowIndex, col: columnIndex })}
                      tabIndex={0}
                      title={`${symbols[rowIndex]} vs ${symbols[columnIndex]}: ${value.toFixed(2)}`}
                      aria-label={`${symbols[rowIndex]} vs ${symbols[columnIndex]}: ${value.toFixed(2)}`}
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
        <span className="sr-only">Colour scale from minus one (blue) to plus one (red).</span>
      </div>
    </Card>
  );
}
