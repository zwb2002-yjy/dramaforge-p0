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
import {
  settingsAccountRoute,
  settingsDefaultsRoute,
  settingsIndexRoute,
  settingsModelsRoute,
  settingsProjectRoute,
  settingsRoute,
  settingsWorkspacesRoute,
} from "./routes/settings";

const projectRouteWithChildren = projectRoute.addChildren([
  projectScriptRoute,
  projectAssetsRoute,
  projectScenesRoute,
  projectSceneWorkspaceRoute,
  projectProductionRoute,
  projectReviewRoute,
  projectEditRoute,
]);

const settingsRouteWithChildren = settingsRoute.addChildren([
  settingsIndexRoute,
  settingsAccountRoute,
  settingsWorkspacesRoute,
  settingsModelsRoute,
  settingsDefaultsRoute,
  settingsProjectRoute,
]);

export const routeTree = rootRoute.addChildren([
  indexRoute,
  projectRouteWithChildren,
  settingsRouteWithChildren,
  designPreviewRoute,
]);
