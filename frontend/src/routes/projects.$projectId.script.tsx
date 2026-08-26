import { createRoute } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

export const projectScriptRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/script",
  component: ScriptPage,
});

function ScriptPage() {
  return (
    <div data-testid="project-script-page" className="qc-project-page">
      <header className="qc-page-heading">
        <p>剧本</p>
        <h1>剧本工作区</h1>
        <span>剧本读取、分场与分镜入口（Phase 1 占位，具体能力随阶段落地）。</span>
      </header>
    </div>
  );
}
