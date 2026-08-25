import { createRoute, redirect } from "@tanstack/react-router";

import { projectRoute } from "./projects.$projectId";

/**
 * Historical quick-mode URLs remain valid bookmarks, but the professional
 * workbench is now the only product surface.  The former staged UI contained
 * DramaForge-side budget and pricing authorization and is intentionally no
 * longer bundled into the application.
 */
export const projectQuickRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/quick",
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/projects/$projectId/production",
      params: { projectId: params.projectId },
      replace: true,
    });
  },
  component: () => null,
});
