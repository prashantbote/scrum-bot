import type { Config } from "tailwindcss";

/**
 * Enterprise Minimal theme. Every color maps to a CSS variable in
 * src/styles/tokens.css — never add hex values here or in components.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    screens: { sm: "640px", md: "768px", lg: "1024px", xl: "1280px" },
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: { DEFAULT: "var(--surface)", muted: "var(--surface-muted)" },
        border: { DEFAULT: "var(--border)", strong: "var(--border-strong)" },
        fg: { DEFAULT: "var(--text)", muted: "var(--text-muted)", subtle: "var(--text-subtle)" },
        teal: {
          50: "var(--teal-50)",
          400: "var(--teal-400)",
          600: "var(--teal-600)",
          700: "var(--teal-700)",
        },
        blue: { 50: "var(--blue-50)", 600: "var(--blue-600)", 700: "var(--blue-700)" },
        warning: { DEFAULT: "var(--warning)", bg: "var(--warning-bg)" },
        danger: { DEFAULT: "var(--danger)", bg: "var(--danger-bg)" },
        neutral: { DEFAULT: "var(--neutral)", bg: "var(--neutral-bg)" },
        overlay: "var(--overlay)",
      },
      borderRadius: { card: "var(--radius-card)", control: "var(--radius-control)" },
      boxShadow: { card: "var(--shadow-card)", popover: "var(--shadow-popover)" },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      fontSize: {
        caption: ["12px", "16px"],
        meta: ["13px", "18px"],
        body: ["14px", "20px"],
        section: ["16px", "24px"],
        title: ["20px", "28px"],
        kpi: ["24px", "32px"],
      },
      height: { control: "32px", row: "36px", topbar: "56px" },
      width: { nav: "220px", "nav-collapsed": "56px" },
      maxWidth: { content: "1440px" },
      transitionDuration: { DEFAULT: "150ms" },
    },
  },
  plugins: [],
};

export default config;
