import { createRoute } from "@tanstack/react-router";

import { EditingWorkspace } from "../features/editing/EditingWorkspace";
import { projectRoute } from "./projects.$projectId";

export const projectEditRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/edit",
  component: EditPage,
});

function EditPage() {
  const { projectId } = projectEditRoute.useParams();
  return <EditingWorkspace projectId={projectId} />;
}
