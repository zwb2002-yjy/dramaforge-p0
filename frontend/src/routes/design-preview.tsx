import { createRoute } from "@tanstack/react-router";

import { LazyDesignPreviewPage } from "./pages";
import { rootRoute } from "./__root";

export const designPreviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/design-preview",
  component: LazyDesignPreviewPage,
});
