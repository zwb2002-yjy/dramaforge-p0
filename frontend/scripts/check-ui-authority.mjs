/** One installed component library across the frontend; explicit media/browser exceptions. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const adoption = JSON.parse(fs.readFileSync(path.join(root, "design/ui-adoption.json"), "utf8"));
const failures = [];
const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
if (!packageJson.dependencies?.antd?.startsWith("6."))
  failures.push("Ant Design 6 must be pinned as the component library");
function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory()
      ? sourceFiles(file)
      : entry.name.endsWith(".tsx")
        ? [path.relative(root, file).split(path.sep).join("/")]
        : [];
  });
}
const surfaces = sourceFiles(path.join(root, "src"));
for (const file of surfaces) {
  const source = fs.readFileSync(path.join(root, file), "utf8");
  if (/\bHTML(?:Details|Dialog)Element\b|\bshowModal\s*\(/.test(source))
    failures.push(
      `${file}: use the library's controlled state instead of retired native disclosure/modal APIs`,
    );
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let usesHeader = false;
  function visit(node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(tree);
      const classAttribute = node.attributes.properties.find(
        (p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "className",
      );
      if (
        classAttribute?.initializer &&
        /\bdf-(?:btn|input|field|tabs|form-group|label|disclosure(?:-body)?)(?![\w-])/.test(
          classAttribute.initializer.getText(tree),
        )
      )
        failures.push(
          `${file}: retired primitive class; use the component API or a feature layout class`,
        );
      if (tag === "Button") {
        const className = node.attributes.properties.find(
          (p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "className",
        );
        if (
          className?.initializer &&
          ts.isStringLiteral(className.initializer) &&
          /(?:^|\s)(primary|ghost|secondary)(?:\s|$)/.test(className.initializer.text) &&
          !node.attributes.properties.some(
            (p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "tone",
          )
        )
          failures.push(`${file}: Button variants must use tone, not legacy CSS classes`);
      }
      if (
        tag === "fieldset" &&
        file !== "src/components/ui/index.tsx" &&
        node.attributes.properties.some(
          (p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "disabled",
        )
      )
        failures.push(`${file}: use Fieldset to disable both library and native controls`);
      if (tag === "Input") {
        const type = node.attributes.properties.find(
          (p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "type",
        );
        if (
          type?.initializer &&
          ts.isStringLiteral(type.initializer) &&
          ["checkbox", "radio", "range", "file", "color"].includes(type.initializer.text)
        )
          failures.push(
            `${file}: use the matching library control instead of Input type=${type.initializer.text}`,
          );
      }
      if (tag === "PageHeader") usesHeader = true;
      if (adoption.pageHeaders.includes(file) && tag === "h1")
        failures.push(`${file}: page titles must use PageHeader`);
      if (
        [
          "button",
          "input",
          "select",
          "textarea",
          "label",
          "details",
          "summary",
          "dialog",
          "table",
        ].includes(tag)
      ) {
        const type = node.attributes.properties.find(
          (p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "type",
        );
        const nativeType =
          type?.initializer && ts.isStringLiteral(type.initializer) ? type.initializer.text : null;
        const className =
          node.attributes.properties
            .find((p) => ts.isJsxAttribute(p) && p.name.getText(tree) === "className")
            ?.getText(tree) ?? "";
        // Media hit targets keep pointer capture and exact pixel geometry.
        const timelineTarget =
          file === "src/features/editing/EditingTimeline.tsx" &&
          tag === "button" &&
          /editing-(?:ruler-seek|timeline-clip|crop-handle)/.test(className);
        const browserInput =
          tag === "input" &&
          ((file === "src/features/script/ScriptImportPanel.tsx" && nativeType === "file") ||
            (file === "src/features/review/VideoReviewTimeline.tsx" && nativeType === "range") ||
            (file === "src/components/ui/index.tsx" && nativeType === "hidden"));
        if (!timelineTarget && !browserInput)
          failures.push(`${file}: use Ant Design via components/ui instead of <${tag}>`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  if (adoption.pageHeaders.includes(file) && !usesHeader)
    failures.push(`${file}: missing PageHeader`);
}
for (const file of [
  ...styleFiles(path.join(root, "src")),
  ...styleFiles(path.join(root, "design")),
]) {
  const css = fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  if (/\.df-(?:btn|input|field|tabs|form-group|label|disclosure(?:-body)?)(?![\w-])/.test(css))
    failures.push(
      `${path.relative(root, file)}: retired primitive selector cannot match Ant Design controls`,
    );
  if (/(?:^|[\s>+~])(?:details|summary)\b/.test(css))
    failures.push(
      `${path.relative(root, file)}: native disclosure selectors must use the current Collapse structure`,
    );
}
function styleFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? styleFiles(file) : entry.name.endsWith(".css") ? [file] : [];
  });
}
for (const file of adoption.layoutStyles) {
  const css = fs.readFileSync(path.join(root, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of css.matchAll(/(?:^|})\s*([^{}]+)\{/g)) {
    for (const selector of match[1].split(",").map((s) => s.trim())) {
      if (
        /^(?:button|input|select|textarea|label)(?:$|[:[.#])/.test(selector) ||
        /^(?:\.df-input|\.df-btn|\.panel)(?:$|:)/.test(selector)
      )
        failures.push(`${file}: ${selector} control recipes belong to the Ant Design theme`);
    }
  }
}
const recipes = fs.readFileSync(path.join(root, "design/components.css"), "utf8");
if (/\b(?:textarea|select)\.df-input|:where\(\s*label\s*\)|input:not\(/.test(recipes))
  failures.push("design/components.css: remove native input/label recipes; use the library theme");
const entry = fs.readFileSync(path.join(root, "src/main.tsx"), "utf8");
if (entry.indexOf('from "./app"') < entry.indexOf('import "./styles/index.css"'))
  failures.push("src/main.tsx: load shared visual styles before App's workspace styles");
if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else
  console.log(
    `UI authority passed: ${surfaces.length} TSX surfaces, ${adoption.pageHeaders.length} page headers; Ant Design is the sole control library.`,
  );
