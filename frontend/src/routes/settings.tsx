import { Navigate, Outlet, createRoute } from "@tanstack/react-router";

import { rootRoute } from "./__root";
import {
  LazyAccountSettingsPage,
  LazyDefaultPreferencesSettingsPage,
  LazyModelConnectionSettingsPage,
  LazyProjectSettingsPage,
  LazyWorkspaceSettingsPage,
} from "./pages";

export const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: () => <Outlet />,
});

export const settingsIndexRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/",
  component: () => <Navigate to="/settings/account" replace />,
});

export const settingsAccountRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/account",
  component: LazyAccountSettingsPage,
});

export const settingsWorkspacesRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/workspaces",
  component: LazyWorkspaceSettingsPage,
});

export const settingsModelsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/models",
  component: LazyModelConnectionSettingsPage,
});

export const settingsDefaultsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/defaults",
  component: LazyDefaultPreferencesSettingsPage,
});

export const settingsProjectRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/projects/$projectId",
  component: LazyProjectSettingsPage,
});
