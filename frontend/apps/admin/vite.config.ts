import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the app is served at http://<org-slug>.localhost:5173 and proxies the API to
// Django with the Host header preserved, so the tenant resolves from the subdomain and session
// cookies + CSRF work same-origin, exactly as in production.
const apiTarget = process.env.VITE_API_BASE_URL ?? "http://localhost:8010";
const proxied = { target: apiTarget, changeOrigin: false, xfwd: true };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Crawl the app *and* the linked workspace packages at startup so every dependency is
  // pre-bundled before the first request. Otherwise a cold dev server discovers deps from
  // packages/* lazily, re-optimises mid-load and serves 504 "Outdated Optimize Dep" chunks
  // (blank page on first load; this broke the e2e job).
  optimizeDeps: {
    entries: [
      "index.html",
      "src/**/*.{ts,tsx}",
      "../../packages/*/src/**/*.{ts,tsx}",
      "!**/*.{test,stories}.{ts,tsx}",
      "!**/test-*.ts",
    ],
  },
  server: {
    port: 5173,
    strictPort: true,
    host: true,
    allowedHosts: [".localhost"],
    proxy: {
      "/api": proxied,
      "/django-admin": proxied,
      "/static": proxied,
      "/healthz": proxied,
      "/readyz": proxied,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
