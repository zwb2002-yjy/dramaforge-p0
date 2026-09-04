import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend, fetchCsrf } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";

/**
 * Phase 1 workspace state: last-view restoration and panel facts are the only
 * frontend-owned persistence. Server facts (scene/shot/asset/node-run) stay in
 * React Query; this hook only touches `UserProjectPreference.workspace_state`.
 */

export const WORKSPACE_VIEWS = [
  "script",
  "assets",
  "scenes",
  "production",
  "review",
  "edit",
] as const;

export type WorkspaceView = (typeof WORKSPACE_VIEWS)[number];

export function workspaceViewFromPath(pathname: string): WorkspaceView | null {
  const match = pathname.match(/\/projects\/[^/]+\/([^/]+)/);
  if (!match) return null;
  const segment = match[1];
  return (WORKSPACE_VIEWS as readonly string[]).includes(segment)
    ? (segment as WorkspaceView)
    : null;
}

type WorkspaceStateRead = {
  state: Record<string, unknown>;
};

function fetchWorkspaceState(projectId: string): Promise<WorkspaceStateRead> {
  return apiGet<WorkspaceStateRead>(`/api/v1/projects/${projectId}/workspace-state`);
}

async function updateWorkspaceState(
  projectId: string,
  state: Record<string, unknown>,
): Promise<WorkspaceStateRead> {
  const csrf = await fetchCsrf();
  return apiSend<WorkspaceStateRead>(
    "PATCH",
    `/api/v1/projects/${projectId}/workspace-state`,
    { state },
    csrf,
  );
}

export function useProjectWorkspaceState(projectId: string) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: queryKeys.workspace.state(projectId),
    queryFn: () => fetchWorkspaceState(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (state: Record<string, unknown>) => updateWorkspaceState(projectId, state),
    onSuccess: (result) => {
      queryClient.setQueryData(["workspace-state", projectId], result);
    },
  });

  const state = (query.data?.state ?? {}) as Record<string, unknown>;
  const lastView =
    typeof state.last_view === "string" &&
    (WORKSPACE_VIEWS as readonly string[]).includes(state.last_view)
      ? (state.last_view as WorkspaceView)
      : null;

  return {
    state,
    lastView,
    isLoading: query.isLoading,
    isSaving: mutation.isPending,
    rememberState(partial: Record<string, unknown>) {
      mutation.mutate(partial);
    },
    rememberLastView(view: WorkspaceView) {
      mutation.mutate({ last_view: view });
    },
  };
}
