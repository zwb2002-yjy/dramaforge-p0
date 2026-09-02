import type { ReactNode } from "react";

type WorkstationShellProps = {
  children: ReactNode;
};

/**
 * Route-specific canonical workspaces own their layout. This boundary is
 * retained for the root route so no legacy shell can reintroduce a second
 * navigation model.
 */
export function WorkstationShell({ children }: WorkstationShellProps) {
  return <>{children}</>;
}
