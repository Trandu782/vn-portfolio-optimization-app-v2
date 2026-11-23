"use client";

/**
 * Correlation heatmap: ticker labels on both axes, a -1..+1 colour legend and a
 * hover state that names the pair ("VHM vs LPB: 0.32") and highlights the
 * hovered row and column.
 */

import { useState } from "react";

import type { CorrelationMatrixMetric } from "@/lib/api";

function correlationColor(value: number): string {
  const clamped = Math.max(-1, Math.min(1, value));
  if (clamped >= 0) {
    return `rgba(220, 38, 38, ${(clamped * 0.7).toFixed(3)})`;
  }
  return `rgba(37, 99, 235, ${(-clamped * 0.7).toFixed(3)})`;
}

export function CorrelationHeatmap({ metric }: { metric: CorrelationMatrixMetric }) {
  const symbols = metric.symbols;
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);
  const hovered =
    hover === null
      ? null
      : `${symbols[hover.row]} vs ${symbols[hover.col]}: ${(metric.matrix[hover.row]?.[hover.col] ?? 0).toFixed(2)}`;

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <h3 className="text-sm font-semibold">Correlation heatmap</h3>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        Pairwise correlation of the analysed symbols. Red is positive, blue is negative.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table
          className="border-collapse text-[10px]"
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
                <th key={symbol} scope="col" className="p-1 font-medium">
                  {symbol}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metric.matrix.map((row, rowIndex) => (
              <tr key={symbols[rowIndex] ?? rowIndex}>
                <th scope="row" className="p-1 text-right font-medium">
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
              "linear-gradient(to right, rgba(37,99,235,0.7), transparent, rgba(220,38,38,0.7))",
            border: "1px solid rgba(107,114,128,0.3)",
          }}
          aria-hidden
        />
        <span aria-hidden>+1</span>
        <span className="sr-only">Colour scale from minus one (blue) to plus one (red).</span>
      </div>
    </div>
  );
}
