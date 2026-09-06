import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes/index";
import { projectRoute } from "./routes/projects.$projectId";
import { projectProductionRoute } from "./routes/projects.$projectId.production";
import { projectScriptRoute } from "./routes/projects.$projectId.script";
import { projectAssetsRoute } from "./routes/projects.$projectId.assets";
import { projectScenesRoute } from "./routes/projects.$projectId.scenes";
import { projectSceneWorkspaceRoute } from "./routes/projects.$projectId.scenes.$sceneId";
import { projectEditRoute } from "./routes/projects.$projectId.edit";
import { projectReviewRoute } from "./routes/projects.$projectId.review";
import { designPreviewRoute } from "./routes/design-preview";

const projectRouteWithChildren = projectRoute.addChildren([
  projectScriptRoute,
  projectAssetsRoute,
  projectScenesRoute,
  projectSceneWorkspaceRoute,
  projectProductionRoute,
  projectReviewRoute,
  projectEditRoute,
]);

export const routeTree = rootRoute.addChildren([
  indexRoute,
  projectRouteWithChildren,
  designPreviewRoute,
]);
