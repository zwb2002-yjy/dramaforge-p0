import { Navigate, Outlet, createRoute } from "@tanstack/react-router";

import { rootRoute } from "./__root";
import { validateSettingsReturnTo } from "../lib/navigationPreferences";
import {
  LazyAccountSettingsPage,
  LazyModelConnectionSettingsPage,
  LazyProjectSettingsPage,
} from "./pages";

export const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  validateSearch: (search: Record<string, unknown>): { returnTo?: string } => ({
    returnTo: validateSettingsReturnTo(search.returnTo),
  }),
  component: () => <Outlet />,
});

export const settingsIndexRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/",
  component: SettingsIndexRedirect,
});

function SettingsIndexRedirect() {
  const { returnTo } = settingsRoute.useSearch();
  return <Navigate to="/settings/models" search={{ returnTo }} replace />;
}

export const settingsAccountRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/account",
  component: LazyAccountSettingsPage,
});

export const settingsWorkspacesRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/workspaces",
  component: () => <Navigate to="/" search={{ panel: "workspace" }} replace />,
});

export const settingsModelsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/models",
  component: LazyModelConnectionSettingsPage,
});

export const settingsDefaultsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/defaults",
  component: LazyModelConnectionSettingsPage,
});

export const settingsProjectRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/projects/$projectId",
  component: LazyProjectSettingsPage,
});
