import { createRoute } from "@tanstack/react-router";

import { ScriptWorkspace } from "../features/script/ScriptWorkspace";
import { projectRoute } from "./projects.$projectId";

export const projectScriptRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/script",
  component: ScriptPage,
});

function ScriptPage() {
  const { projectId } = projectScriptRoute.useParams();
  return <ScriptWorkspace projectId={projectId} />;
}
