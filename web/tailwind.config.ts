import type { Config } from "tailwindcss"

// Design tokens come straight from the spec. Keep names in lockstep with the
// CSS variables in app/globals.css so we can use either Tailwind classes or
// `var(--mesh-gold)` interchangeably.
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Mesh brand palette
        bg:      "#080808",
        surface: "#111111",
        border:  "#1C1C1C",
        text:    { DEFAULT: "#F0F0F0", muted: "#666666" },
        gold:    "#C9A84C",
        blue:    "#4A9EFF",
        green:   "#3ECF8E",
        red:     "#FF4444",
        purple:  "#9B59D4",
      },
      fontFamily: {
        sans:    ["var(--font-inter)", "ui-sans-serif", "system-ui"],
        display: ["var(--font-display)", "var(--font-inter)", "system-ui"],
        mono:    ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.25)",
        pop:  "0 8px 28px rgba(201,168,76,0.18), 0 2px 6px rgba(0,0,0,0.4)",
      },
      borderRadius: {
        DEFAULT: "10px",
        lg: "14px",
        sm: "6px",
      },
    },
  },
  plugins: [],
}
export default config
