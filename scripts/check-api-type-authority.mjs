// Contract authority gate: the OpenAPI-generated schema names are the single
// source for HTTP response/request shapes. A frontend module that re-declares
// one of those names as a hand-written object type is drifting from the
// generated contract, so the duplication fails here instead of silently
// compiling.

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const frontendSrc = path.join(repoRoot, "frontend", "src");
const generatedPath = path.join(frontendSrc, "shared", "api", "generated.ts");

const generated = readFileSync(generatedPath, "utf8");
const schemasStart = generated.indexOf("schemas: {");
if (schemasStart === -1) {
  console.error("[api:authority] cannot locate the schemas section in generated.ts");
  process.exit(1);
}

// Brace-match the whole schemas block so path-item keys cannot leak in.
const openBrace = generated.indexOf("{", schemasStart);
let depth = 1;
let cursor = openBrace + 1;
while (cursor < generated.length && depth > 0) {
  const char = generated[cursor];
  if (char === "{") depth++;
  else if (char === "}") depth--;
  cursor++;
}
const schemasBody = generated.slice(openBrace + 1, cursor - 1);

const schemaNames = new Set();
for (const line of schemasBody.split(/\r?\n/)) {
  const match = /^ {8}([A-Za-z_$][\w$]*): /.exec(line);
  if (match) schemaNames.add(match[1]);
}
if (schemaNames.size === 0) {
  console.error("[api:authority] generated.ts exposes no schemas");
  process.exit(1);
}

const SKIPPED_DIRS = new Set(["node_modules", "dist", ".git"]);
const handWritten = /^export\s+(?:type\s+([A-Za-z_$][\w$]*)\s*=\s*\{|interface\s+([A-Za-z_$][\w$]*)\s*\{)/gm;

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (SKIPPED_DIRS.has(entry)) continue;
    const full = path.join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) yield* walk(full);
    else if (/\.tsx?$/.test(entry)) yield full;
  }
}

const failures = [];
for (const file of walk(frontendSrc)) {
  if (path.resolve(file) === generatedPath) continue;
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(handWritten)) {
    const name = match[1] ?? match[2];
    if (schemaNames.has(name)) {
      failures.push(`${path.relative(repoRoot, file)} redeclares generated schema ${name}`);
    }
  }
}

if (failures.length > 0) {
  console.error("API type authority check FAILED:");
  for (const failure of failures.sort()) console.error(`  - ${failure}`);
  console.error(
    "Use components[\"schemas\"][\"<Name>\"] from frontend/src/shared/api/generated.ts instead.",
  );
  process.exit(1);
}
console.log(`API type authority check passed (${schemaNames.size} generated schemas).`);
