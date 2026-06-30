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
  // Use the automatic JSX runtime (matches the vite prod build) so .tsx
  // sources authored without `import React` — including the shared
  // @marshellis/canopy-ui primitives consumed here — transform correctly.
  // Without this, vitest's esbuild defaults to the classic runtime and the
  // package's Button/Badge/etc throw "React is not defined".
  esbuild: { jsx: "automatic" },
  // @marshellis/canopy-ui ships .tsx/.ts source (no prebuilt dist), so it must be
  // transformed rather than externalized as a normal node_modules dep.
  server: { deps: { inline: ["@marshellis/canopy-ui"] } },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
  },
})
