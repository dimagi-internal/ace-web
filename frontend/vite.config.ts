import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// Asset URLs are served under the labs ALB tenant path `/ace/*` in prod,
// and the docker-compose dev container also runs Django with
// FORCE_SCRIPT_NAME=/ace by default — so the Vite dev server uses the
// same base path for prod parity. `bun run dev` lands you at
// http://localhost:5173/ace/ and the proxy below forwards `/ace/api`,
// `/ace/auth`, etc. through to the local Django on :8000 unchanged.
const BACKEND = "http://127.0.0.1:8000"
const BACKEND_WS = "ws://127.0.0.1:8000"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  base: "/ace/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    port: 5173,
    proxy: {
      // Backend HTTP routes — forward unchanged so Django keeps the
      // /ace prefix it's expecting via FORCE_SCRIPT_NAME.
      "/ace/api": BACKEND,
      "/ace/auth": BACKEND,
      "/ace/admin": BACKEND,
      "/ace/share": BACKEND,
      // Channels WebSocket. Strip the /ace prefix to match the routing
      // registration (which is ws/sessions/<slug>/ without the prefix);
      // mirrors the nginx /ace/ws/ location block in prod.
      "/ace/ws": {
        target: BACKEND_WS,
        ws: true,
        rewrite: (p) => p.replace(/^\/ace/, ""),
      },
      // Bare-prefix variants for users who run docker compose with
      // FORCE_SCRIPT_NAME='' (Django at root).
      "/api": BACKEND,
      "/auth": BACKEND,
      "/ws": {target: BACKEND_WS, ws: true},
    },
  },
})
