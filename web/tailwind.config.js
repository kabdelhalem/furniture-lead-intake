/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces — a cool "drafting paper", not the usual warm cream.
        paper: "#EEF1ED",
        panel: "#FBFCFA",
        "panel-2": "#F4F7F2",
        line: "#DBE1DB",
        "line-strong": "#C6CEC5",

        // Ink — a deep pine near-black, and its softer/fainter steps.
        ink: "#1B2420",
        "ink-soft": "#4E5A53",
        "ink-faint": "#7C857D",

        // Brand / action / priority — a single reserved teal-pine, kept off the
        // confidence channel so semantic hues never get muddied by chrome.
        brand: "#0E5A54",
        "brand-deep": "#093F3A",
        "brand-tint": "#DCE9E6",

        // Confidence semantics — their own channel. Each is always paired with a
        // glyph + word in the UI, never carried by hue alone.
        commit: "#3F7A54",
        "commit-ink": "#2C5C3D",
        "commit-bg": "#E6EFE6",
        review: "#B9772A",
        "review-ink": "#875313",
        "review-bg": "#F7EAD6",
        // Severe — the alarm floor: conflict, hallucination risk, declined match.
        // A vermilion kept distinct from the amber review hue.
        alarm: "#B23A2E",
        "alarm-ink": "#8A281F",
        "alarm-bg": "#F4DBD6",
        muted: "#8A928C",
        "muted-bg": "#EAEEE9",
        // Human-touched fields read as "a person signed this" — brand-family.
        human: "#0E5A54",
        "human-bg": "#DCE9E6",
      },
      fontFamily: {
        // Two families, shared geometric-grotesque DNA. Display carries body too
        // (used at smaller sizes); mono is reserved for data — SKUs, dimensions,
        // field paths, confidence figures — where a fixed advance reads as honest.
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        mono: ['"Space Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
      },
      boxShadow: {
        panel: "0 1px 2px rgba(27,36,32,0.04), 0 6px 20px -12px rgba(27,36,32,0.18)",
        lift: "0 2px 6px rgba(27,36,32,0.06), 0 18px 40px -20px rgba(27,36,32,0.28)",
      },
      borderRadius: {
        card: "10px",
      },
      keyframes: {
        "rise-in": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "rise-in": "rise-in 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) both",
      },
    },
  },
  plugins: [],
};
