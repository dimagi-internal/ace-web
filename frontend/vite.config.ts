import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Asset URLs are prefixed with /ace/ so the app can be served behind the
  // labs ALB at path prefix /ace/*. In local dev Vite's proxy handles /api/*
  // directly, and BASE_URL falls back to '/' for API URL construction.
  base: "/ace/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
})
