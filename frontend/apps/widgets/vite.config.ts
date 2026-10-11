import { defineConfig } from "vitest/config";

// Embeddable web components (E24) built as one ES module served from the CDN:
// <script type="module" src="https://cdn.tutortrack.app/widgets.js" data-org="slug"></script>
export default defineConfig({
  build: {
    lib: { entry: "src/index.ts", formats: ["es"], fileName: () => "widgets.js" },
    target: "es2020",
  },
  // Local playground and the dev WIDGETS_SCRIPT_URL (http://localhost:5175/src/index.ts).
  server: { port: 5175, cors: true },
  test: { environment: "jsdom" },
});
