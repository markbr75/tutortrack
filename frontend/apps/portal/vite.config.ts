import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const proxied = {
  target: process.env.VITE_API_BASE_URL ?? "http://localhost:8010",
  changeOrigin: false,
  xfwd: true,
};

// Client, student, tutor and affiliate portals (one installable PWA with role shells),
// served at /portal/ on the organisation's host so sign-in, sessions and the tenant are
// shared with the admin app. PWA manifest/service worker arrive in E16.
export default defineConfig({
  base: "/portal/",
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
    port: 5174,
    strictPort: true,
    host: true,
    allowedHosts: [".localhost"],
    proxy: { "/api": proxied },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
