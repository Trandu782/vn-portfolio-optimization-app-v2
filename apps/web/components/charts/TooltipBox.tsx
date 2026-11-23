"use client";

import type { ReactNode } from "react";

import { TOOLTIP_CLASS } from "@/lib/chart-theme";

/** A styled HTML tooltip body shared by every chart (dark mode follows the app). */
export function TooltipBox({ children }: { children: ReactNode }) {
  return <div className={TOOLTIP_CLASS}>{children}</div>;
}
