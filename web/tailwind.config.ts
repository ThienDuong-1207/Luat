import type { Config } from "tailwindcss";

// Mọi giá trị trỏ về token trong app/globals.css (spec 15.3)
const config: Config = {
  content: ["./app/**/*.tsx", "./components/**/*.tsx"],
  theme: {
    extend: {
      colors: {
        ink: "var(--ink)",
        paper: "var(--paper)",
        surface: "var(--surface)",
        yellow: "var(--yellow)",
        blue: "var(--blue)",
        pink: "var(--pink)",
        green: "var(--green)",
        red: "var(--red)",
        orange: "var(--orange)",
        muted: "var(--muted)",
        "red-soft": "var(--red-soft)",
        "green-soft": "var(--green-soft)",
      },
      boxShadow: {
        brutal: "var(--shadow)",
        "brutal-sm": "var(--shadow-sm)",
        "brutal-lg": "var(--shadow-hover)",
        "brutal-press": "var(--shadow-press)",
      },
      borderWidth: { 3: "3px" },
      borderRadius: { brutal: "var(--radius)" },
      fontFamily: { sans: ["var(--font-sans)"], mono: ["var(--font-mono)"] },
      maxWidth: { chat: "760px" },
    },
  },
};

export default config;
