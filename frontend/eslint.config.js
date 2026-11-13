import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

const networkApis = ["fetch", "EventSource", "XMLHttpRequest", "WebSocket"];
const networkMessage = "Use the unified transport in src/lib/api.ts.";

export default tseslint.config(
  {
    ignores: ["dist", "coverage", "playwright-report", "test-results", "tmp"],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/lib/api.ts"],
    rules: {
      "no-restricted-globals": [
        "error",
        ...networkApis.map((name) => ({ name, message: networkMessage })),
      ],
      // Only known browser globals: unrelated business objects may use these names.
      // Object aliases, dynamic property access and reflection still require review.
      "no-restricted-properties": [
        "error",
        ...["window", "globalThis", "self"].flatMap((object) =>
          networkApis.map((property) => ({ object, property, message: networkMessage })),
        ),
      ],
    },
  },
  {
    files: ["src/routes/**/*.{ts,tsx}"],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
);
