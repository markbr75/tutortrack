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
