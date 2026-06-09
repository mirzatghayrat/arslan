/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        amber: { DEFAULT: "#f59e0b", strong: "#d97706" },
        brand: { DEFAULT: "#FF8E24", dim: "#785C3E", text: "#FFEED6" },
        ink: { 900: "#0f0f23", 800: "#1a1a3e", 700: "#2d1b4e" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
