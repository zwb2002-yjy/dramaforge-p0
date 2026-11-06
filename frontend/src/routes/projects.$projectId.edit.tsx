import { createRoute, useBlocker } from "@tanstack/react-router";
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
    ...(typeof search.clipId === "string" ? { clipId: search.clipId } : {}),
  }),
  component: EditPage,
});

function EditPage() {
  const { projectId } = projectEditRoute.useParams();
  const { sessionId, clipId } = projectEditRoute.useSearch();
  const navigate = projectEditRoute.useNavigate();
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
        ("sessionId" in current.search ? current.search.sessionId : undefined) !==
          ("sessionId" in next.search ? next.search.sessionId : undefined)),
    enableBeforeUnload: dirty,
    disabled: !dirty,
    withResolver: true,
  });
  return (
    <>
      <LazyEditingWorkspace
        key={`${projectId}:${sessionId}:${discardRevision}`}
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
            void navigate({ search: { sessionId, clipId: selected }, replace: true });
        }}
        onSessionSelected={(selectedSessionId) =>
          navigate({ search: { sessionId: selectedSessionId } })
        }
        onSessionCreated={(createdSessionId) =>
          navigate({ search: { sessionId: createdSessionId } })
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
