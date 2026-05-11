import path from "path"
import { defineConfig } from "vitest/config"

// Standalone vitest config — separate from vite.config.ts so the prod
// build doesn't pull jsdom/RTL into its dependency graph. Just enough
// to run *.test.ts(x) under apps' src/ folder.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
  },
})
