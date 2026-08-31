import { createRoute } from "@tanstack/react-router";

import { EditingWorkspace } from "../features/editing/EditingWorkspace";
import { projectRoute } from "./projects.$projectId";

export const projectEditRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/edit",
  validateSearch: (search: Record<string, unknown>) => ({
    sessionId: typeof search.sessionId === "string" ? search.sessionId : undefined,
  }),
  component: EditPage,
});

function EditPage() {
  const { projectId } = projectEditRoute.useParams();
  const { sessionId } = projectEditRoute.useSearch();
  const navigate = projectEditRoute.useNavigate();
  return (
    <EditingWorkspace
      projectId={projectId}
      sessionId={sessionId}
      onSessionCreated={(createdSessionId) => navigate({ search: { sessionId: createdSessionId } })}
    />
  );
}
