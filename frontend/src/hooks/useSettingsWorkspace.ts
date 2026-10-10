import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import {
  getSelectedWorkspaceId,
  listWorkspaceProjects,
  listWorkspaces,
  setSelectedWorkspaceId as persistSelectedWorkspaceId,
} from "../lib/api";
import { queryKeys } from "../lib/queryKeys";

export function useSettingsWorkspace(onSelect?: (workspaceId: string | null) => void) {
  const workspaces = useQuery({
    queryKey: queryKeys.workspace.list(),
    queryFn: listWorkspaces,
  });
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    getSelectedWorkspaceId,
  );
  const selectWorkspace = useCallback(
    (workspaceId: string | null) => {
      persistSelectedWorkspaceId(workspaceId);
      setSelectedWorkspaceId(workspaceId);
      onSelect?.(workspaceId);
    },
    [onSelect],
  );

  useEffect(() => {
    if (!selectedWorkspaceId && workspaces.data?.[0]) selectWorkspace(workspaces.data[0].id);
    if (
      selectedWorkspaceId &&
      workspaces.data &&
      !workspaces.data.some((workspace) => workspace.id === selectedWorkspaceId)
    ) {
      selectWorkspace(workspaces.data[0]?.id ?? null);
    }
  }, [selectWorkspace, selectedWorkspaceId, workspaces.data]);

  const projects = useQuery({
    queryKey: queryKeys.workspace.projects(selectedWorkspaceId),
    queryFn: () => listWorkspaceProjects(selectedWorkspaceId!),
    enabled: Boolean(selectedWorkspaceId),
  });

  return { workspaces, projects, selectedWorkspaceId, selectWorkspace };
}
