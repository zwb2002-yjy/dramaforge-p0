// Verify that the committed frontend API types are reproducible without
// requiring Git metadata.  This is used by both host CI and source-less
// quality images, where `git diff` cannot inspect the checkout.

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const generated = path.join(
  repoRoot,
  "frontend",
  "src",
  "shared",
  "api",
  "generated.ts",
);

const expected = readFileSync(generated);
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const result = spawnSync(npm, ["run", "api:generate"], {
  cwd: path.join(repoRoot, "frontend"),
  stdio: "inherit",
});

try {
  if (result.status !== 0) {
    process.exitCode = result.status ?? 1;
  } else {
    const actual = readFileSync(generated);
    if (!actual.equals(expected)) {
      console.error(
        "[api:check] generated.ts is stale; run `npm run api:generate` and commit the result.",
      );
      process.exitCode = 1;
    } else {
      console.log("[api:check] generated.ts is up to date.");
    }
  }
} finally {
  // Keep the check side-effect free, including when the generator fails after
  // partially writing the target.
  writeFileSync(generated, expected);
}
