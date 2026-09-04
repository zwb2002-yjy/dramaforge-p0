import { createRoute } from "@tanstack/react-router";

import { LazySceneStoryboardWall } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectScenesRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/scenes",
  component: ScenesPage,
});

function ScenesPage() {
  const { projectId } = projectScenesRoute.useParams();
  return <LazySceneStoryboardWall projectId={projectId} />;
}
