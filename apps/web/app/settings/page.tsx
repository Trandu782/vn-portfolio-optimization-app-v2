"use client";

import { type FormEvent, useEffect, useState } from "react";

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

  const inputClass =
    "mt-1 w-40 rounded-md border border-gray-300 px-3 py-2 text-sm disabled:opacity-50 dark:border-gray-700 dark:bg-gray-900";

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-300">
          These values are used in every calculation and saved in your browser. They are
          placeholders until you set them to values you trust.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-5">
        <div>
          <label htmlFor="brokerage-fee" className="block text-sm font-medium">
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
            className={inputClass}
          />
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Check your broker&apos;s fee schedule.
          </p>
        </div>

        <div>
          <label htmlFor="risk-free" className="block text-sm font-medium">
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
            className={inputClass}
          />
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Use a government bond yield you consider appropriate for your horizon.
          </p>
        </div>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {saved && <p className="text-sm text-green-600 dark:text-green-400">Saved.</p>}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={!ready}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Save
          </button>
          <button
            type="button"
            onClick={handleReset}
            disabled={!ready}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:hover:bg-gray-900"
          >
            Reset to defaults
          </button>
        </div>
      </form>
    </section>
  );
}
