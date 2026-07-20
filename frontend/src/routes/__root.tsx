import { Outlet, createRootRoute } from "@tanstack/react-router";

import { WorkstationShell } from "../components/workstation/WorkstationShell";

export const rootRoute = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  return (
    <WorkstationShell>
      <Outlet />
    </WorkstationShell>
  );
}
