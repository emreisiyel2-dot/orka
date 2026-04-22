import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        base: {
          DEFAULT: "#0a0a0f",
          50: "#111118",
          100: "#1a1a24",
          200: "#22222e",
          300: "#2a2a38",
        },
        border: {
          DEFAULT: "#1e1e2a",
          light: "#2a2a3a",
        },
        healthy: "#22c55e",
        working: "#eab308",
        error: "#ef4444",
        info: "#3b82f6",
        assigned: "#6366f1",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
