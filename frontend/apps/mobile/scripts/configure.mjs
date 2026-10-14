#!/usr/bin/env node
// Turn a white-label configuration (E16-T11) into capacitor.config.json and the icon source.
//
//   node scripts/configure.mjs                       # the generic "TutorTrack" app
//   node scripts/configure.mjs --config white-label.json
//   node scripts/configure.mjs --url https://acme.tutortrack.app/api/v1/public/mobile-app
//   node scripts/configure.mjs --print appId         # print one value of the result
//
// The configuration comes from `manage.py mobile_app_config --org <slug>` or the public
// endpoint above (both built from the organisation's E24 brand kit). Only https URLs on the
// configured host are loaded in the shell; everything else opens in the system browser.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

export const GENERIC = {
  white_label: false,
  appId: "app.tutortrack.portal",
  appName: "TutorTrack",
  serverUrl: "",
  allowNavigation: ["*.tutortrack.app"],
  primaryColour: "#2563eb",
  onPrimary: "#ffffff",
  backgroundColour: "#ffffff",
  iconUrl: "",
  organisation: null,
};

const APP_ID = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;
const HEX = /^#[0-9a-fA-F]{6}$/;

/** Validate a white-label configuration; throws with the first problem. */
export function validate(config) {
  const merged = { ...GENERIC, ...config };
  if (!APP_ID.test(merged.appId)) throw new Error(`Invalid appId ${merged.appId}`);
  if (!merged.appName || merged.appName.length > 30)
    throw new Error("appName must be 1-30 characters");
  for (const key of ["primaryColour", "onPrimary", "backgroundColour"]) {
    if (!HEX.test(merged[key])) throw new Error(`${key} must be a #rrggbb colour`);
  }
  if (merged.serverUrl) {
    const url = new URL(merged.serverUrl);
    if (url.protocol !== "https:") throw new Error("serverUrl must be https");
  }
  if (merged.iconUrl && new URL(merged.iconUrl).protocol !== "https:") {
    throw new Error("iconUrl must be https");
  }
  return merged;
}

/** The Capacitor configuration for a (validated) white-label configuration. */
export function capacitorConfig(config) {
  const c = validate(config);
  const server = c.serverUrl
    ? { url: c.serverUrl, cleartext: false, allowNavigation: c.allowNavigation }
    : { allowNavigation: c.allowNavigation };
  return {
    appId: c.appId,
    appName: c.appName,
    // The generic app bundles the organisation picker (www/); white-label apps load their
    // organisation's portal, so login cookies, tenancy by host and the service worker work
    // exactly as in the installed PWA.
    webDir: "www",
    server,
    android: { allowMixedContent: false, backgroundColor: c.backgroundColour },
    ios: { contentInset: "always", backgroundColor: c.backgroundColour },
    plugins: {
      SplashScreen: {
        launchShowDuration: 800,
        backgroundColor: c.primaryColour,
        showSpinner: false,
      },
      StatusBar: {
        backgroundColor: c.primaryColour,
        style: c.onPrimary === "#ffffff" ? "DARK" : "LIGHT",
      },
    },
  };
}

async function load(args) {
  const at = (flag) => {
    const i = args.indexOf(flag);
    return i >= 0 ? args[i + 1] : undefined;
  };
  if (at("--config")) return JSON.parse(await readFile(at("--config"), "utf8"));
  if (at("--url")) {
    const url = new URL(at("--url"));
    if (url.protocol !== "https:") throw new Error("--url must be https");
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`${url} answered ${response.status}`);
    return response.json();
  }
  return GENERIC;
}

async function main(args) {
  const config = validate(await load(args));
  const printKey = args.includes("--print") ? args[args.indexOf("--print") + 1] : undefined;
  if (printKey) {
    process.stdout.write(`${config[printKey] ?? ""}\n`);
    return;
  }
  const capacitor = capacitorConfig(config);
  await writeFile(join(ROOT, "capacitor.config.json"), `${JSON.stringify(capacitor, null, 2)}\n`);
  await writeFile(join(ROOT, "www", "app-config.json"), `${JSON.stringify(config, null, 2)}\n`);
  if (config.iconUrl) {
    const response = await fetch(config.iconUrl);
    if (!response.ok) throw new Error(`Couldn't download the app icon (${response.status})`);
    await mkdir(join(ROOT, "assets"), { recursive: true });
    await writeFile(join(ROOT, "assets", "icon.png"), Buffer.from(await response.arrayBuffer()));
  }
  process.stdout.write(`Configured ${capacitor.appId} (${capacitor.appName}).\n`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv.slice(2)).catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  });
}
