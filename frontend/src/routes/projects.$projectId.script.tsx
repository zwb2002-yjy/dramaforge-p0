import { createRoute } from "@tanstack/react-router";

import { LazyScriptWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectScriptRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/script",
  component: ScriptPage,
});

function ScriptPage() {
  const { projectId } = projectScriptRoute.useParams();
  const navigate = projectScriptRoute.useNavigate();
  return (
    <LazyScriptWorkspace
      projectId={projectId}
      onOpenScene={(sceneId) =>
        void navigate({
          to: "/projects/$projectId/scenes/$sceneId",
          params: { projectId, sceneId },
          search: { shotId: undefined, tool: undefined },
        })
      }
    />
  );
}
