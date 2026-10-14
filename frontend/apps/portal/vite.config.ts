import { createHash } from "node:crypto";
import { resolve } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { build, type Plugin } from "vite";
import { defineConfig } from "vitest/config";

const proxied = {
  target: process.env.VITE_API_BASE_URL ?? "http://localhost:8010",
  changeOrigin: false,
  xfwd: true,
};

const BASE = "/portal/";
const ICONS = ["icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png"];

/** Builds src/sw/sw.ts into dist/sw.js after the app (E16-T08), with the list of files to
 * precache (the hashed bundle, index.html and icons) and a version derived from it, so a
 * new deploy installs a new worker and drops the old shell cache. A small hand-written
 * worker instead of Workbox: one file, no extra dependencies (ADR 0023). */
function serviceWorker(): Plugin {
  let root = process.cwd();
  let outDir = "dist";
  return {
    name: "tutortrack-service-worker",
    apply: "build",
    configResolved(config) {
      root = config.root;
      outDir = resolve(config.root, config.build.outDir);
    },
    async writeBundle(_options, bundle) {
      const files = Object.keys(bundle).filter(
        (file) => !file.endsWith(".map") && /\.(html|js|css|woff2?|png|svg|webp)$/.test(file),
      );
      const precache = [...files, ...ICONS].map((file) => BASE + file);
      const version = createHash("sha256").update(precache.sort().join("\n")).digest("hex");
      await build({
        configFile: false,
        root,
        logLevel: "warn",
        publicDir: false,
        define: {
          __PRECACHE__: JSON.stringify(precache),
          __SW_VERSION__: JSON.stringify(version.slice(0, 12)),
        },
        build: {
          outDir,
          emptyOutDir: false,
          copyPublicDir: false,
          sourcemap: false,
          lib: {
            entry: resolve(root, "src/sw/sw.ts"),
            formats: ["iife"],
            name: "portalServiceWorker",
            fileName: () => "sw.js",
          },
        },
      });
    },
  };
}

// Client, student, tutor and affiliate portals (one installable PWA with role shells),
// served at /portal/ on the organisation's host so sign-in, sessions and the tenant are
// shared with the admin app. The service worker (offline, background sync, push) is
// built by the plugin above.
export default defineConfig({
  base: BASE,
  plugins: [react(), tailwindcss(), serviceWorker()],
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
      "!src/sw/**",
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
