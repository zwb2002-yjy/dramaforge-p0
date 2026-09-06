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
  return <LazyScriptWorkspace projectId={projectId} />;
}
