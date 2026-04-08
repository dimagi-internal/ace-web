import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  // Emitted asset URLs are prefixed with Django's STATIC_URL so WhiteNoise
  // serves them from STATIC_ROOT/assets/*. Without this the built index.html
  // references /assets/*, which is not mounted anywhere and silently falls
  // through to the SPA catch-all route — serving HTML to the browser in
  // response to .js requests and breaking the page.
  base: "/static/",
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
