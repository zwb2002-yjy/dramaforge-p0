// Evaluate the actual router after Vite production transforms. UI visibility and
// dev-server tests cannot establish which routes a release registers.
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
import { build } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const probeId = "\0production-route-audit";
const bundle = await build({
  root,
  mode: "production",
  configFile: path.join(root, "vite.config.ts"),
  logLevel: "warn",
  plugins: [
    {
      name: "production-route-audit",
      configResolved(config) {
        // Keep the production transforms; only coalesce output for evaluation.
        delete config.build.rollupOptions.output.manualChunks;
      },
      resolveId(id) {
        if (id === "production-route-audit") return probeId;
      },
      load(id) {
        if (id !== probeId) return;
        return `import { router } from ${JSON.stringify(path.join(root, "src/router.tsx"))};
          globalThis.__productionRouteAudit = {
            dev: import.meta.env.DEV,
            production: import.meta.env.PROD,
            paths: Object.keys(router.routesByPath).sort(),
          };`;
      },
    },
  ],
  build: {
    write: false,
    minify: true,
    rollupOptions: {
      input: "production-route-audit",
      output: {
        format: "iife",
        inlineDynamicImports: true,
      },
    },
  },
});
const outputs = Array.isArray(bundle) ? bundle : [bundle];
const entry = outputs
  .flatMap((item) => item.output)
  .find((item) => item.type === "chunk" && item.isEntry);
assert.ok(entry, "Vite must emit the production router probe");
const browser = await chromium.launch({
  executablePath: process.env.DRAMAFORGE_E2E_EXECUTABLE_PATH || undefined,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
try {
  const page = await browser.newPage();
  // Give browser-only state a real origin; every request is intercepted locally.
  await page.route("**/*", (route) =>
    route.fulfill({ contentType: "text/html", body: "<html></html>" }),
  );
  await page.goto("http://production-route-audit.invalid/");
  await page.addScriptTag({ content: entry.code });
  const result = await page.evaluate(() => globalThis.__productionRouteAudit);
  assert.equal(result.dev, false);
  assert.equal(result.production, true);
  assert.ok(result.paths.includes("/"));
  assert.ok(result.paths.includes("/projects/$projectId/review"));
  assert.ok(result.paths.includes("/settings/models"));
  assert.ok(
    !result.paths.some((route) => route.includes("design-preview")),
    "development route registered in production",
  );
  console.log("[routes:production]", JSON.stringify(result));
} finally {
  await browser.close();
}
