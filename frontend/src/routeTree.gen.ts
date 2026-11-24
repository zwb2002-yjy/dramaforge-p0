import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes/index";
import { projectRoute } from "./routes/projects.$projectId";
import { projectProductionRoute } from "./routes/projects.$projectId.production";
import { projectFilesRoute } from "./routes/projects.$projectId.files";
import { projectResearchRoute } from "./routes/projects.$projectId.research";
import { projectScriptRoute } from "./routes/projects.$projectId.script";
import { projectAssetsRoute } from "./routes/projects.$projectId.assets";
import { projectScenesRoute } from "./routes/projects.$projectId.scenes";
import { projectSceneWorkspaceRoute } from "./routes/projects.$projectId.scenes.$sceneId";
import { projectEditRoute } from "./routes/projects.$projectId.edit";
import { projectReviewRoute } from "./routes/projects.$projectId.review";
import { designPreviewRoute } from "./routes/design-preview";
import { knowledgeRoute } from "./routes/knowledge";
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
  projectProductionRoute,
  projectFilesRoute,
  projectResearchRoute,
  projectScriptRoute,
  projectAssetsRoute,
  projectScenesRoute,
  projectSceneWorkspaceRoute,
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

// The design-system showcase is a development tool: production builds do not
// register the route, so a first-release user cannot reach it at all.
export const routeTree = rootRoute.addChildren([
  indexRoute,
  knowledgeRoute,
  projectRouteWithChildren,
  settingsRouteWithChildren,
  ...(import.meta.env.DEV ? [designPreviewRoute] : []),
]);
