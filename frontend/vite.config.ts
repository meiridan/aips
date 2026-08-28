import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Output goes straight into the Python package: Railway builds via railpack
// (uv + Procfile) with no build-time hook, so the bundle is committed and
// served by FastAPI's /assets mount. See CLAUDE.md + `make ui`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../maya/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/media": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
