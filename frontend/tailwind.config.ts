import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        night: "#06070d",
        panel: "#0b0d1a",
        panel2: "#151729",
        accent: "#8b5cf6",
        glow: "#a5b4fc",
        gold: "#38bdf8",
        mint: "#34d399",
        sky: "#22d3ee",
        rose: "#f472b6",
      },
    },
  },
  plugins: [],
};

export default config;
