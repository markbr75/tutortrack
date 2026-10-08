import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const proxied = {
  target: process.env.VITE_API_BASE_URL ?? "http://localhost:8010",
  changeOrigin: false,
  xfwd: true,
};

// Client, student, tutor and affiliate portals (one installable PWA with role shells).
// PWA manifest/service worker arrive in E16; role shells in E15/E16.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    host: true,
    allowedHosts: [".localhost"],
    proxy: { "/api": proxied },
  },
});
