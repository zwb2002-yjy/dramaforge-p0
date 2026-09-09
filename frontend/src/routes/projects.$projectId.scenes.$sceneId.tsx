import { createRoute, useBlocker } from "@tanstack/react-router";
import { useState } from "react";

import { UnsavedChangesDialog } from "../features/scenes/UnsavedChangesDialog";
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
  const [hasUnsavedDesign, setHasUnsavedDesign] = useState(false);
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => hasUnsavedDesign && current.pathname !== next.pathname,
    enableBeforeUnload: hasUnsavedDesign,
    disabled: !hasUnsavedDesign,
    withResolver: true,
  });
  return (
    <>
      <LazySceneWorkspace
        projectId={projectId}
        sceneId={sceneId}
        initialShotId={shotId}
        openDirector={tool === "director"}
        onDirtyStateChange={setHasUnsavedDesign}
        onOpenEditing={() =>
          void navigate({
            to: "/projects/$projectId/edit",
            params: { projectId },
            search: { sessionId: undefined },
          })
        }
      />
      {blocker.status === "blocked" && (
        <UnsavedChangesDialog
          title="离开场景前先处理当前草稿"
          detail="当前镜头有未保存的设计。返回保存可保留修改；确认放弃后才会离开当前场景。"
          discardLabel="放弃并离开"
          onReturnToSave={blocker.reset}
          onDiscard={blocker.proceed}
        />
      )}
    </>
  );
}
