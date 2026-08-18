import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes/index";
import { projectRoute } from "./routes/projects.$projectId";
import { projectProductionRoute } from "./routes/projects.$projectId.production";
import { projectQuickRoute } from "./routes/projects.$projectId.quick";
import { designPreviewRoute } from "./routes/design-preview";

const projectRouteWithChildren = projectRoute.addChildren([
  projectQuickRoute,
  projectProductionRoute,
]);

export const routeTree = rootRoute.addChildren([
  indexRoute,
  projectRouteWithChildren,
  designPreviewRoute,
]);
