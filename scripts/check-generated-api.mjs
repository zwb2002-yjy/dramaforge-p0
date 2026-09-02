// Verify that the committed frontend API types are reproducible without
// requiring Git metadata. The authoritative caller is the source-less
// frontend quality image, which receives the backend-exported contract.

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
  // Windows cannot spawn a .cmd shim without a shell; Linux/macOS keep the
  // direct process path so the check remains deterministic there.
  shell: process.platform === "win32",
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
