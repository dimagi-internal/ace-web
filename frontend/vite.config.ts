import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
      // Mirror the nginx /ace/ws/ location block so prod-parity WS URLs
      // (wss://.../ace/ws/sessions/<slug>/) also work in local dev. The
      // rewrite strips the /ace prefix before forwarding to Channels,
      // whose routing registers ws/sessions/<slug>/ without the prefix.
      "/ace/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        rewrite: (path) => path.replace(/^\/ace/, ""),
      },
    },
  },
})
