import type { Config } from "tailwindcss";

/*
 * Hex rather than `var(--x)` so opacity modifiers (`bg-ink-soft/50`) keep
 * working; the same values are exported as CSS vars in `globals.css` for the
 * places that need an inline style.
 */
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#050A14", // canvas
          soft: "#0D1424", // card
          raised: "#1B2A4A", // elevated / brand-strong
          inset: "#090E1A", // wells and tracks
          line: "#1B2437", // hairline, white 7% flattened
        },
        brand: {
          DEFAULT: "#4F8FE8",
          strong: "#1B2A4A",
        },
        paper: "#FBFBFD",
        critical: "#EF4444",
        serious: "#F97316",
        notable: "#F59E0B",
        minor: "#8EA4BD",
        faint: "#5C738A",
        up: "#10B981",
        down: "#EF4444",
      },
      boxShadow: {
        glow: "0 0 18px rgba(79, 143, 232, 0.25)",
        bento: "0 8px 30px rgba(5, 10, 20, 0.55)",
      },
      borderRadius: {
        card: "16px",
      },
      fontFamily: {
        sans: [
          "Poppins",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
