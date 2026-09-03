import { createRoute } from "@tanstack/react-router";

import { LazySceneWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectSceneWorkspaceRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/scenes/$sceneId",
  component: SceneWorkspacePage,
});

function SceneWorkspacePage() {
  const { projectId, sceneId } = projectSceneWorkspaceRoute.useParams();
  return <LazySceneWorkspace projectId={projectId} sceneId={sceneId} />;
}
