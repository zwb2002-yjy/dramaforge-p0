// Contract authority gate: OpenAPI-generated schemas are the single source for
// HTTP response/request shapes. Besides exact-name redeclarations, API client
// modules may not export hand-written object DTOs under different names. The
// small allowlist below is reserved for frontend-only composed state.

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
const exportedType = /^export\s+type\s+([A-Za-z_$][\w$]*)\s*=\s*([^\r\n;]+)/gm;
const exportedInterface =
  /^export\s+interface\s+([A-Za-z_$][\w$]*)(?:\s+extends\s+[^\{]+)?\s*\{/gm;
const localApiObjectTypes = new Map([
  ["frontend/src/lib/api.ts", new Set(["HealthResponse", "ResolvedProjectWorkspace"])],
  ["frontend/src/features/review/repairApi.ts", new Set(["RepairSubmission"])],
  ["frontend/src/features/shots/api.ts", new Set(["PreparedShotExecution"])],
]);

function isApiClient(relativePath) {
  return (
    relativePath === "frontend/src/lib/api.ts" ||
    /\/(?:api|[^/]*Api|[^/]*-api)\.ts$/.test(relativePath)
  );
}

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
  const relativePath = path.relative(repoRoot, file).replaceAll(path.sep, "/");
  const generatedAliases = new Set();
  for (const match of source.matchAll(exportedType)) {
    const name = match[1];
    const declaration = match[2].trim();
    const referencedAlias = /^([A-Za-z_$][\w$]*)\b/.exec(declaration)?.[1];
    const generatedDerived =
      /\bcomponents\s*\[\s*["']schemas["']\s*\]/.test(declaration) ||
      (referencedAlias !== undefined && generatedAliases.has(referencedAlias));
    if (generatedDerived) generatedAliases.add(name);
    let objectPrefix = declaration;
    while (/^(?:Readonly|Partial|Required)\s*</.test(objectPrefix)) {
      objectPrefix = objectPrefix.replace(/^(?:Readonly|Partial|Required)\s*<\s*/, "");
    }
    const handWrittenObject = objectPrefix.startsWith("{") || objectPrefix.startsWith("Record<");
    if (schemaNames.has(name) && !generatedDerived) {
      failures.push(`${relativePath} redeclares generated schema ${name}`);
    } else if (
      isApiClient(relativePath) &&
      handWrittenObject &&
      !localApiObjectTypes.get(relativePath)?.has(name)
    ) {
      failures.push(
        `${relativePath} exports hand-written API object ${name}; alias or derive a generated schema`,
      );
    }
  }
  for (const match of source.matchAll(exportedInterface)) {
    const name = match[1];
    if (schemaNames.has(name)) {
      failures.push(`${relativePath} redeclares generated schema ${name}`);
    } else if (
      isApiClient(relativePath) &&
      !localApiObjectTypes.get(relativePath)?.has(name)
    ) {
      failures.push(
        `${relativePath} exports hand-written API object ${name}; alias or derive a generated schema`,
      );
    }
  }
}

if (failures.length > 0) {
  console.error("API type authority check FAILED:");
  for (const failure of failures.sort()) console.error(`  - ${failure}`);
  console.error(
    "Use or derive components[\"schemas\"][\"<Name>\"] from frontend/src/shared/api/generated.ts instead.",
  );
  process.exit(1);
}
console.log(`API type authority check passed (${schemaNames.size} generated schemas).`);
