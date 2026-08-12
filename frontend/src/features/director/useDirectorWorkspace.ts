import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ensureDirectorWorkspace } from "./api";

export const directorWorkspaceKey = (projectId: string) =>
  ["director-workspace", projectId] as const;

export function useDirectorWorkspace(projectId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: directorWorkspaceKey(projectId),
    queryFn: () => ensureDirectorWorkspace(projectId),
    enabled: Boolean(projectId && projectId !== "demo"),
    refetchInterval: (state) => {
      const status = state.state.data?.workflow.status;
      return status && ["trial_running", "production_running", "assembling", "final_review"].includes(status)
        ? 2_500
        : false;
    },
  });

  return {
    ...query,
    refresh: () => queryClient.invalidateQueries({ queryKey: directorWorkspaceKey(projectId) }),
  };
}
