import { createRoute } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

export const projectQuickRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/quick",
  component: QuickModePage,
});

function QuickModePage() {
  const { projectId } = projectQuickRoute.useParams();
  return (
    <div data-testid="quick-mode">
      <h2>快速模式</h2>
      <p>
        与专业工作台共享 Project <code>{projectId}</code>（S2 接入 Brief/Plan）。
      </p>
    </div>
  );
}
