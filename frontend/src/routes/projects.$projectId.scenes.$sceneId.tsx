import { createRoute } from "@tanstack/react-router";

import { SceneWorkspace } from "../features/scenes/SceneWorkspace";
import { projectRoute } from "./projects.$projectId";

export const projectSceneWorkspaceRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/scenes/$sceneId",
  component: SceneWorkspacePage,
});

function SceneWorkspacePage() {
  const { projectId, sceneId } = projectSceneWorkspaceRoute.useParams();
  return <SceneWorkspace projectId={projectId} sceneId={sceneId} />;
}
