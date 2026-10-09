/** Guard the migrated surface, not a claim that every domain widget is generic. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const adoption = JSON.parse(fs.readFileSync(path.join(root, "design/ui-adoption.json"), "utf8"));
const failures = [];
for (const file of new Set([...adoption.controls, ...adoption.pageHeaders])) {
  const source = fs.readFileSync(path.join(root, file), "utf8");
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let usesHeader = false;
  function visit(node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(tree);
      if (tag === "PageHeader") usesHeader = true;
      if (adoption.pageHeaders.includes(file) && tag === "h1")
        failures.push(`${file}: page titles must use PageHeader`);
      if (
        adoption.controls.includes(file) &&
        ["button", "input", "select", "textarea", "label"].includes(tag)
      ) {
        const type = node.attributes.properties.find(
          (p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "type",
        );
        const nativeType =
          type?.initializer && ts.isStringLiteral(type.initializer) ? type.initializer.text : null;
        // File/colour/range/radio widgets have distinct native interaction semantics.
        if (!(tag === "input" && ["file", "color", "range", "radio"].includes(nativeType)))
          failures.push(`${file}: use shared UI primitive instead of <${tag}>`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  if (adoption.pageHeaders.includes(file) && !usesHeader)
    failures.push(`${file}: missing PageHeader`);
}
for (const file of adoption.layoutStyles) {
  const css = fs.readFileSync(path.join(root, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of css.matchAll(/(?:^|})\s*([^{}]+)\{/g)) {
    for (const selector of match[1].split(",").map((s) => s.trim())) {
      if (
        /^(?:button|input|select|textarea|label)(?:$|[:[.#])/.test(selector) ||
        /^(?:\.df-input|\.df-btn|\.panel)(?:$|:)/.test(selector)
      )
        failures.push(`${file}: ${selector} defaults belong in design/components.css`);
    }
  }
}
const entry = fs.readFileSync(path.join(root, "src/main.tsx"), "utf8");
if (entry.indexOf('from "./app"') < entry.indexOf('import "./styles/index.css"'))
  failures.push("src/main.tsx: load shared visual styles before App's workspace styles");
if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else
  console.log(
    `UI authority passed: ${adoption.controls.length} control surfaces, ${adoption.pageHeaders.length} page headers; one primitive style owner.`,
  );
