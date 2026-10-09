import { createRoute, useBlocker } from "@tanstack/react-router";
import { useRef, useState } from "react";

import { UnsavedChangesDialog } from "../features/scenes/UnsavedChangesDialog";
import { LazySceneWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectSceneWorkspaceRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/scenes/$sceneId",
  validateSearch: (search: Record<string, unknown>) => ({
    shotId: typeof search.shotId === "string" ? search.shotId : undefined,
    tool:
      search.tool === "director" || search.tool === "prompts" || search.tool === "generate"
        ? search.tool
        : undefined,
    ...(search.review === true ? { review: true as const } : {}),
  }),
  component: SceneWorkspacePage,
});

function SceneWorkspacePage() {
  const { projectId, sceneId } = projectSceneWorkspaceRoute.useParams();
  const { shotId, tool, review } = projectSceneWorkspaceRoute.useSearch();
  const navigate = projectSceneWorkspaceRoute.useNavigate();
  const [hasUnsavedDesign, setHasUnsavedDesign] = useState(false);
  const dirtyRef = useRef(false);
  const [discardRevision, setDiscardRevision] = useState(0);
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => {
      const before = "shotId" in current.search ? current.search.shotId : undefined;
      const after = "shotId" in next.search ? next.search.shotId : undefined;
      return dirtyRef.current && (current.pathname !== next.pathname || before !== after);
    },
    enableBeforeUnload: hasUnsavedDesign,
    disabled: !hasUnsavedDesign,
    withResolver: true,
  });
  return (
    <>
      <LazySceneWorkspace
        key={`${projectId}:${sceneId}:${discardRevision}`}
        projectId={projectId}
        sceneId={sceneId}
        initialShotId={shotId}
        openDirector={tool === "director"}
        openPrompts={tool === "prompts"}
        openGenerate={tool === "generate"}
        openCandidates={review}
        onDirtyStateChange={(dirty) => {
          dirtyRef.current = dirty;
          setHasUnsavedDesign(dirty);
        }}
        onSelectedShotChange={(selected) => {
          dirtyRef.current = false;
          setHasUnsavedDesign(false);
          void navigate({
            search: (previous) => ({ ...previous, shotId: selected }),
            replace: true,
          });
        }}
        onOpenOverview={() =>
          void navigate({
            to: "/projects/$projectId/scenes",
            params: { projectId },
          })
        }
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
          onDiscard={() => {
            dirtyRef.current = false;
            setHasUnsavedDesign(false);
            setDiscardRevision((value) => value + 1);
            blocker.proceed();
          }}
        />
      )}
    </>
  );
}
