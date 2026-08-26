import { createRoute } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

export const projectAssetsRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/assets",
  component: AssetsPage,
});

function AssetsPage() {
  return (
    <div data-testid="project-assets-page" className="qc-project-page">
      <header className="qc-page-heading">
        <p>资产</p>
        <h1>项目资产</h1>
        <span>角色、场景、道具与风格资产的版本化卡片（Phase 1 占位，资产卡能力随阶段落地）。</span>
      </header>
    </div>
  );
}
