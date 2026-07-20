import { createRoute } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

export const projectProductionRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/production",
  component: ProductionPage,
});

function ProductionPage() {
  const { projectId } = projectProductionRoute.useParams();
  return (
    <div data-testid="production-mode">
      <h2>专业生产</h2>
      <p>Shot 生产与审核工作台壳（S4）。当前 Project：{projectId}</p>
    </div>
  );
}
