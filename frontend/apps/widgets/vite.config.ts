import { defineConfig } from "vitest/config";

// Embeddable web components (E24) built as one ES module served from the CDN:
// <script type="module" src="https://cdn.tutortrack.app/widgets.js" data-org="slug"></script>
export default defineConfig({
  build: {
    lib: { entry: "src/index.ts", formats: ["es"], fileName: () => "widgets.js" },
    target: "es2020",
  },
  test: { environment: "jsdom" },
});
