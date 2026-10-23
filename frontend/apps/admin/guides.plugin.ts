import { readFileSync } from "node:fs";
import { extname } from "node:path";
import { fileURLToPath } from "node:url";

import type { Plugin } from "vite";

import { indexGuide } from "./src/success/guideIndex";

// The HTML guides (docs/guides) ship with the admin app at /guides/, with routes.json
// mapping each app page to the guide section about it (the Help panel links there).
const DIR = fileURLToPath(new URL("../../../docs/guides/", import.meta.url));
const GUIDES = ["user-guide.html", "admin-guide.html", "api-guide.html"];
const FILES = [...GUIDES, "guide.css"];
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
};

const read = (name: string) => readFileSync(`${DIR}${name}`);

function routesJson(): string {
  return JSON.stringify(GUIDES.flatMap((name) => indexGuide(name, read(name).toString())));
}

export function guides(): Plugin {
  return {
    name: "tutortrack-guides",
    configureServer(server) {
      server.middlewares.use("/guides", (req, res, next) => {
        const name = (req.url ?? "/").split("?")[0]?.replace(/^\//, "") || "user-guide.html";
        if (name !== "routes.json" && !FILES.includes(name)) return next();
        res.setHeader("Content-Type", TYPES[extname(name)] ?? "text/plain");
        res.end(name === "routes.json" ? routesJson() : read(name));
      });
    },
    generateBundle() {
      for (const name of FILES) {
        this.emitFile({ type: "asset", fileName: `guides/${name}`, source: read(name) });
      }
      this.emitFile({ type: "asset", fileName: "guides/routes.json", source: routesJson() });
    },
  };
}
