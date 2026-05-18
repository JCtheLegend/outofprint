/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        serif: ["'Playfair Display'", "Georgia", "serif"],
        body: ["'Lora'", "Georgia", "serif"],
      },
      colors: {
        cream: "#f5f0e8",
        ink: "#1a1614",
        rust: "#8B3A2A",
        "rust-light": "#f5e8e4",
        gold: "#b8860b",
        muted: "#6b6560",
        border: "#d4c9b8",
      },
    },
  },
  plugins: [],
};
