// node --test scripts/  (no dependencies needed)
import assert from "node:assert/strict";
import { test } from "node:test";

import { GENERIC, capacitorConfig, validate } from "./configure.mjs";

test("the generic app bundles the organisation picker", () => {
  const config = capacitorConfig(GENERIC);
  assert.equal(config.appId, "app.tutortrack.portal");
  assert.equal(config.webDir, "www");
  assert.equal(config.server.url, undefined);
});

test("a white-label app loads its organisation's portal over https", () => {
  const config = capacitorConfig({
    white_label: true,
    appId: "app.tutortrack.tenant.brightminds",
    appName: "Bright Minds",
    serverUrl: "https://brightminds.tutortrack.app/portal/",
    allowNavigation: ["brightminds.tutortrack.app"],
    primaryColour: "#0f766e",
    onPrimary: "#ffffff",
  });
  assert.equal(config.server.url, "https://brightminds.tutortrack.app/portal/");
  assert.deepEqual(config.server.allowNavigation, ["brightminds.tutortrack.app"]);
  assert.equal(config.plugins.SplashScreen.backgroundColor, "#0f766e");
});

test("unsafe or malformed configurations are refused", () => {
  assert.throws(() => validate({ appId: "Not An Id" }), /appId/);
  assert.throws(() => validate({ serverUrl: "http://example.test/portal/" }), /https/);
  assert.throws(() => validate({ primaryColour: "red" }), /colour/);
  assert.throws(() => validate({ appName: "x".repeat(31) }), /appName/);
});
