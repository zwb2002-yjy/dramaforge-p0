import { createRoute, useBlocker } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { fetchProject } from "../features/project/api";
import { queryKeys } from "../lib/queryKeys";
import { useCallback, useRef, useState } from "react";
import { Button, Dialog } from "../components/ui";
import { timelineCopy as copy } from "../features/editing/timelineCopy";

import { LazyEditingWorkspace } from "./pages";
import { projectRoute } from "./projects.$projectId";

export const projectEditRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/edit",
  validateSearch: (search: Record<string, unknown>) => ({
    sessionId: typeof search.sessionId === "string" ? search.sessionId : undefined,
    ...(typeof search.goalId === "string" && typeof search.planId === "string"
      ? { goalId: search.goalId, planId: search.planId }
      : {}),
    ...(typeof search.clipId === "string" ? { clipId: search.clipId } : {}),
  }),
  component: EditPage,
});

function EditPage() {
  const { projectId } = projectEditRoute.useParams();
  const { sessionId, clipId, goalId, planId } = projectEditRoute.useSearch();
  const boundSearch = goalId && planId ? { goalId, planId } : {};
  const navigate = projectEditRoute.useNavigate();
  const project = useQuery({
    queryKey: queryKeys.project.detail(projectId),
    queryFn: () => fetchProject(projectId),
    retry: false,
  });
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const saveAction = useRef<HTMLButtonElement>(null);
  const focusSaveAfterClose = useRef(false);
  const [discardRevision, setDiscardRevision] = useState(0);
  const onDirtyStateChange = useCallback((value: boolean) => {
    dirtyRef.current = value;
    setDirty(value);
  }, []);
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) =>
      dirtyRef.current &&
      (current.pathname !== next.pathname ||
        ("planId" in current.search ? current.search.planId : undefined) !==
          ("planId" in next.search ? next.search.planId : undefined) ||
        ("sessionId" in current.search ? current.search.sessionId : undefined) !==
          ("sessionId" in next.search ? next.search.sessionId : undefined)),
    enableBeforeUnload: dirty,
    disabled: !dirty,
    withResolver: true,
  });
  return (
    <>
      <LazyEditingWorkspace
        workType={project.data?.work_type}
        projectScopeUnavailable={!project.isSuccess}
        key={`${projectId}:${sessionId}:${goalId}:${planId}:${discardRevision}`}
        deliveryPlan={goalId && planId ? { master_run_id: goalId, plan_id: planId } : undefined}
        projectId={projectId}
        sessionId={sessionId}
        clipId={clipId}
        onDirtyStateChange={onDirtyStateChange}
        saveActionRef={saveAction}
        onOpenShot={(sceneId, shotId, selectedClipId) =>
          void navigate({
            to: "/projects/$projectId/scenes/$sceneId",
            params: { projectId, sceneId },
            search: {
              shotId,
              tool: undefined,
              editSessionId: sessionId,
              editClipId: selectedClipId,
            },
          })
        }
        onSelectedClipChange={(selected) => {
          if (selected !== clipId)
            void navigate({
              search: { ...boundSearch, sessionId, clipId: selected },
              replace: true,
            });
        }}
        onSessionSelected={(selectedSessionId) =>
          navigate({ search: { ...boundSearch, sessionId: selectedSessionId } })
        }
        onSessionCreated={(createdSessionId) =>
          navigate({ search: { ...boundSearch, sessionId: createdSessionId } })
        }
      />
      <Dialog
        open={blocker.status === "blocked"}
        title={copy.leaveTitle}
        onClose={() => blocker.reset?.()}
        afterClose={() => {
          if (focusSaveAfterClose.current) {
            focusSaveAfterClose.current = false;
            saveAction.current?.focus();
          }
        }}
        actions={
          <>
            <Button
              tone="primary"
              onClick={() => {
                focusSaveAfterClose.current = true;
                blocker.reset?.();
              }}
            >
              {copy.returnToSave}
            </Button>
            <Button
              tone="danger"
              onClick={() => {
                dirtyRef.current = false;
                setDirty(false);
                setDiscardRevision((value) => value + 1);
                blocker.proceed?.();
              }}
            >
              {copy.discardAndLeave}
            </Button>
          </>
        }
      >
        <p>{copy.leaveDetail}</p>
      </Dialog>
    </>
  );
}
