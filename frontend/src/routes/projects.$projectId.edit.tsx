import { createRoute } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

export const projectEditRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/edit",
  component: EditPage,
});

function EditPage() {
  return (
    <div data-testid="project-edit-page" className="qc-project-page">
      <header className="qc-page-heading">
        <p>剪辑</p>
        <h1>剪辑工作区</h1>
        <span>OpenCut 时间线与成片（Phase 1 占位，剪辑能力随 OpenCut 阶段落地）。</span>
      </header>
    </div>
  );
}
