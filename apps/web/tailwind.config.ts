import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        shell: "var(--bg-shell)",
        page: "var(--bg-page)",
        surface: "var(--bg-surface)",
        raised: "var(--bg-raised)",
        hairline: "var(--border-hairline)",
        strong: "var(--border-strong)",
        fg: "var(--fg-primary)",
        "fg-secondary": "var(--fg-secondary)",
        "fg-muted": "var(--fg-muted)",
        accent: "var(--accent)",
        "accent-hover": "var(--accent-hover)",
        "accent-subtle": "var(--accent-subtle)",
        "accent-ink": "var(--accent-ink)",
        cta: "var(--cta-bg)",
        "cta-fg": "var(--cta-fg)",
        "cta-hover": "var(--cta-hover)",
        positive: "var(--positive)",
        "positive-subtle": "var(--positive-subtle)",
        negative: "var(--negative)",
        "negative-subtle": "var(--negative-subtle)",
        warn: "var(--warn)",
        "warn-border": "var(--warn-border)",
        "warn-subtle": "var(--warn-subtle)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      transitionTimingFunction: {
        unslop: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
