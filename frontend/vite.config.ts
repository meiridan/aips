/// <reference types="vitest" />
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
  // The auth screens are the first components with rendering tests, so the
  // suite needs a DOM. The pure-logic tests (wizardReducer, validation) run
  // fine under it too.
  test: {
    environment: "jsdom",
    globals: false,
    restoreMocks: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/media": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
