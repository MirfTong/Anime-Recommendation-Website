/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      boxShadow: {
        glow: "0 20px 50px rgba(168, 85, 247, 0.18)",
      },
    },
  },
  plugins: [],
};
