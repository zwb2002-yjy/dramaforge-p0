import { createRouter } from "@tanstack/react-router";

import { routeTree } from "./routeTree.gen";
import { RouteFailure, RouteMissing, RoutePending } from "./components/routing/RouteFeedback";

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  defaultPendingComponent: RoutePending,
  defaultErrorComponent: RouteFailure,
  defaultNotFoundComponent: RouteMissing,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
