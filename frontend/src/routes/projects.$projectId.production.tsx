import { createRoute } from "@tanstack/react-router";

import { LazyProductionPage } from "./pages";
import { projectRoute } from "./projects.$projectId";

/**
 * Cross-scene overview: progress, workflow, explicit experiment branches and
 * creative settings. Shot creation and the Editing export keep their own routes.
 */
export const projectProductionRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/production",
  validateSearch: (search: Record<string, unknown>) => ({
    view: search.view === "experiments" ? ("experiments" as const) : undefined,
    shotId: typeof search.shotId === "string" ? search.shotId : undefined,
  }),
  component: ProductionRoutePage,
});

function ProductionRoutePage() {
  const { projectId } = projectProductionRoute.useParams();
  const { view, shotId } = projectProductionRoute.useSearch();
  return (
    <LazyProductionPage
      key={`${projectId}:${view}:${shotId}`}
      projectId={projectId}
      initialView={view}
      initialShotId={shotId}
    />
  );
}
