import { createRoute } from "@tanstack/react-router";

import { LazyProductionPage } from "./pages";
import { projectRoute } from "./projects.$projectId";

/**
 * Phase 10 (plan 03 §89): the production page is a cross-scene Production
 * Monitor. Script Import, budget main panel and the former large storyboard
 * workspace belong to the Scene Workbench and are no longer here; the
 * ProfessionalWorkbench (assets / experiments / review / director board /
 * OpenCut) and the dedicated EditSession export remain in their canonical
 * workspaces.
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
