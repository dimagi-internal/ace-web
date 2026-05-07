import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// Asset URLs are served under the labs ALB tenant path `/ace/*` in prod,
// and the docker-compose dev container also runs Django with
// FORCE_SCRIPT_NAME=/ace by default — so the Vite dev server uses the
// same base path for prod parity. `bun run dev` lands you at
// http://localhost:5173/ace/ and the proxy below forwards `/ace/api`,
// `/ace/auth`, etc. through to the local Django.
//
// Backend host port defaults to 8001 (not 8000) so ace-web's
// docker-compose stack coexists with CommCare HQ / connect-labs / other
// Django dev servers that conventionally bind 8000. Override with
// `VITE_BACKEND_PORT` if a teammate runs ace-web on a different port.
const BACKEND_PORT = process.env.VITE_BACKEND_PORT ?? "8001"
const BACKEND = `http://127.0.0.1:${BACKEND_PORT}`
const BACKEND_WS = `ws://127.0.0.1:${BACKEND_PORT}`

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
