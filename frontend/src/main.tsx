import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../design/tokens.css";
import "../design/theme.css";
import "../design/typography.css";
import "../design/components.css";
import "./styles/index.css";
// Load the visual foundation before App brings in scoped workspace styles.
import { App } from "./app";

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
