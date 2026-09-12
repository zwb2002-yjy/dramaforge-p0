import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet, createRoute, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { ProjectWorkspaceShell } from "../components/workstation/ProjectWorkspaceShell";
import { useProjectWorkspaceState, workspaceViewFromPath } from "../hooks/useProjectWorkspaceState";
import { ApiError, fetchProject } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function ProjectLayout() {
  const { projectId } = projectRoute.useParams();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const view = workspaceViewFromPath(pathname);
  const atRoot = view === null;
  const workspaceState = useProjectWorkspaceState(projectId);
  const project = useQuery({
    queryKey: queryKeys.project.detail(projectId),
    queryFn: async () => {
      try {
        return await fetchProject(projectId);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: projectId !== "demo",
    retry: false,
  });

  const lastRemembered = useRef<string | null>(null);
  useEffect(() => {
    if (view && lastRemembered.current !== view) {
      lastRemembered.current = view;
      workspaceState.rememberLastView(view);
    }
  }, [view, workspaceState]);

  if (atRoot && !workspaceState.isLoading) {
    const restoreTarget = workspaceState.lastView ?? "scenes";
    return <Navigate to={`/projects/$projectId/${restoreTarget}`} params={{ projectId }} replace />;
  }

  const projectRead = project.data ?? undefined;
  const activeView = view ?? "overview";

  return (
    <ProjectWorkspaceShell
      projectId={projectId}
      projectName={projectRead?.name ?? (projectId === "demo" ? "演示项目" : "短剧项目")}
      activeView={activeView}
    >
      {project.isError && (
        <div className="flash err">
          无法读取项目事实：
          {project.error instanceof Error ? project.error.message : "未知错误"}
        </div>
      )}
      {atRoot ? <p className="muted">正在恢复上次创作位置…</p> : <Outlet />}
    </ProjectWorkspaceShell>
  );
}
