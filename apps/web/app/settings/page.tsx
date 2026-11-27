"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { inputClass } from "@/components/ui/Field";
import { fromPercent, toPercent, type UserSettings } from "@/lib/user-settings";
import { useUserSettings } from "@/lib/user-settings-context";

export default function SettingsPage() {
  const { settings, bounds, ready, updateSettings, resetSettings } = useUserSettings();

  const [feePercent, setFeePercent] = useState("");
  const [riskFreePercent, setRiskFreePercent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setFeePercent(String(toPercent(settings.brokerageFeeRate)));
      setRiskFreePercent(String(toPercent(settings.riskFreeRate)));
    }
  }, [settings]);

  function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaved(false);

    if (!bounds) {
      setError("Settings are still loading. Try again in a moment.");
      return;
    }

    const fee = Number(feePercent);
    const riskFree = Number(riskFreePercent);
    if (!Number.isFinite(fee) || !Number.isFinite(riskFree)) {
      setError("Enter numeric values for both fields.");
      return;
    }

    const next: UserSettings = {
      brokerageFeeRate: fromPercent(fee),
      riskFreeRate: fromPercent(riskFree),
    };

    if (
      next.brokerageFeeRate < bounds.brokerageFeeRate.min ||
      next.brokerageFeeRate > bounds.brokerageFeeRate.max
    ) {
      const min = toPercent(bounds.brokerageFeeRate.min);
      const max = toPercent(bounds.brokerageFeeRate.max);
      setError(`Brokerage fee must be between ${min}% and ${max}%.`);
      return;
    }

    if (next.riskFreeRate < bounds.riskFreeRate.min || next.riskFreeRate > bounds.riskFreeRate.max) {
      const min = toPercent(bounds.riskFreeRate.min);
      const max = toPercent(bounds.riskFreeRate.max);
      setError(`Risk-free rate must be between ${min}% and ${max}%.`);
      return;
    }

    updateSettings(next);
    setSaved(true);
  }

  function handleReset() {
    setError(null);
    setSaved(false);
    resetSettings();
  }

  return (
    <section className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-[28px] leading-[1.15] font-medium tracking-[-0.015em] text-fg">
          Settings
        </h1>
        <p className="max-w-2xl text-sm leading-6 text-fg-secondary">
          These values are used in every calculation and saved in your browser. They are
          placeholders until you set them to values you trust.
        </p>
      </div>

      <Card className="max-w-xl p-6">
        <form onSubmit={handleSave} className="space-y-5">
          <div className="space-y-1.5">
            <label htmlFor="brokerage-fee" className="block text-sm font-medium text-fg">
              Brokerage fee per side (%)
            </label>
            <input
              id="brokerage-fee"
              type="number"
              inputMode="decimal"
              step="0.01"
              min={bounds ? toPercent(bounds.brokerageFeeRate.min) : undefined}
              max={bounds ? toPercent(bounds.brokerageFeeRate.max) : undefined}
              value={feePercent}
              onChange={(event) => setFeePercent(event.target.value)}
              disabled={!ready}
              className={`${inputClass} w-44 font-mono tabular-nums`}
            />
            <p className="text-xs text-fg-muted">
              Check your broker&apos;s fee schedule.
            </p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="risk-free" className="block text-sm font-medium text-fg">
              Risk-free rate (% per year)
            </label>
            <input
              id="risk-free"
              type="number"
              inputMode="decimal"
              step="0.01"
              min={bounds ? toPercent(bounds.riskFreeRate.min) : undefined}
              max={bounds ? toPercent(bounds.riskFreeRate.max) : undefined}
              value={riskFreePercent}
              onChange={(event) => setRiskFreePercent(event.target.value)}
              disabled={!ready}
              className={`${inputClass} w-44 font-mono tabular-nums`}
            />
            <p className="text-xs text-fg-muted">
              Use a government bond yield you consider appropriate for your horizon.
            </p>
          </div>

          {error && <p className="text-sm text-negative">{error}</p>}
          {saved && <p className="text-sm text-positive">Saved</p>}

          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Button type="submit" variant="primary" disabled={!ready}>
              Save
            </Button>
            <Button type="button" variant="secondary" onClick={handleReset} disabled={!ready}>
              Reset to defaults
            </Button>
          </div>
        </form>
      </Card>
    </section>
  );
}
