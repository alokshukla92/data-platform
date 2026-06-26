/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0e1a",
          900: "#0f1525",
          800: "#161e34",
          700: "#1f2a45",
        },
        brand: {
          400: "#5b8cff",
          500: "#3b6cf6",
          600: "#2d56d4",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
