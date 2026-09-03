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
  component: ProductionRoutePage,
});

function ProductionRoutePage() {
  const { projectId } = projectProductionRoute.useParams();
  return <LazyProductionPage projectId={projectId} />;
}
