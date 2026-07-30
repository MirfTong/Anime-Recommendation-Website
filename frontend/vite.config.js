import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./test/setup.js",
    include: ["test/**/*.ui.test.{js,jsx}"],
    restoreMocks: true,
  },
  build: {
    outDir: "../static/react",
    emptyOutDir: true,
  },
});
