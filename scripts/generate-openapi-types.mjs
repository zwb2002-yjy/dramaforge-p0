// Cross-platform launcher for api:generate.
// Resolves a Python interpreter the same way scripts/generate_openapi_types.py does
// (backend/.venv on Windows; `python` elsewhere — CI provides it via `uv`), then
// spawns that generator. This keeps `npm run api:generate` runnable without
// requiring a global `python` on PATH, and works on Windows dev + Linux CI.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const generator = path.join(repoRoot, "scripts", "generate_openapi_types.py");

let python;
if (process.platform === "win32") {
  const venv = path.join(repoRoot, "backend", ".venv", "Scripts", "python.exe");
  python = existsSync(venv) ? venv : (process.env.CI ? "python" : "py");
} else {
  python = "python";
}

const res = spawnSync(python, [generator], { stdio: "inherit", cwd: repoRoot });
process.exit(res.status ?? 1);
