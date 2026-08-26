import { createRoute } from "@tanstack/react-router";

import { SceneStoryboardWall } from "../features/workbench/SceneStoryboardWall";
import { projectRoute } from "./projects.$projectId";

export const projectScenesRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/scenes",
  component: ScenesPage,
});

function ScenesPage() {
  const { projectId } = projectScenesRoute.useParams();
  return <SceneStoryboardWall projectId={projectId} />;
}
