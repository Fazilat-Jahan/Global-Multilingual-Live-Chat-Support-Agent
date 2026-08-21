import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#d9e6ff",
          500: "#3b6df0",
          600: "#2f57cc",
          700: "#2646a8",
        },
      },
    },
  },
  plugins: [],
};

export default config;
