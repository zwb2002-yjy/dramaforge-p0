import { createRoute } from "@tanstack/react-router";

import { LazySceneWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectSceneWorkspaceRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/scenes/$sceneId",
  validateSearch: (search: Record<string, unknown>) => ({
    shotId: typeof search.shotId === "string" ? search.shotId : undefined,
    tool: search.tool === "director" ? "director" : undefined,
  }),
  component: SceneWorkspacePage,
});

function SceneWorkspacePage() {
  const { projectId, sceneId } = projectSceneWorkspaceRoute.useParams();
  const { shotId, tool } = projectSceneWorkspaceRoute.useSearch();
  const navigate = projectSceneWorkspaceRoute.useNavigate();
  return (
    <LazySceneWorkspace
      projectId={projectId}
      sceneId={sceneId}
      initialShotId={shotId}
      openDirector={tool === "director"}
      onOpenEditing={() =>
        void navigate({
          to: "/projects/$projectId/edit",
          params: { projectId },
          search: { sessionId: undefined },
        })
      }
    />
  );
}
