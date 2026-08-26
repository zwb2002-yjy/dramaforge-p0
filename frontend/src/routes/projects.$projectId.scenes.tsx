import { createRoute } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

export const projectScenesRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/scenes",
  component: ScenesPage,
});

function ScenesPage() {
  return (
    <div data-testid="project-scenes-page" className="qc-project-page">
      <header className="qc-page-heading">
        <p>场景</p>
        <h1>场景总览</h1>
        <span>故事板墙与场景工作区（Phase 1 占位，场景墙随 Scene Workspace 阶段落地）。</span>
      </header>
    </div>
  );
}
