import { useQuery } from "@tanstack/react-query";
import { Outlet, createRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { ProjectWorkspaceShell } from "../components/workstation/ProjectWorkspaceShell";
import { useProjectWorkspaceState, workspaceViewFromPath } from "../hooks/useProjectWorkspaceState";
import { ApiError, fetchProject } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { getRememberedProjectPath, rememberProjectPath } from "../lib/navigationPreferences";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function ProjectLayout() {
  const { projectId } = projectRoute.useParams();
  const navigate = useNavigate();
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
    if (view) rememberProjectPath(projectId, pathname);
    if (view && lastRemembered.current !== `${projectId}:${view}`) {
      lastRemembered.current = `${projectId}:${view}`;
      workspaceState.rememberLastView(view);
    }
  }, [view, workspaceState, projectId, pathname]);

  // Restore the last view with an imperative replace instead of rendering a
  // <Navigate> element, and require that the router's current pathname is still
  // the project root. During a navigation away (for example the permanent
  // Settings entry) the router reports the next route at the parent path while
  // the old view is still committing; restoring there would outrun the user's
  // own navigation and replace it.
  const currentPathname = useRouterState({ select: (state) => state.location.pathname });
  const atProjectRoot = currentPathname === `/projects/${projectId}`;
  useEffect(() => {
    if (!atProjectRoot || workspaceState.isLoading) return;
    const restoreTarget = workspaceState.lastView ?? "scenes";
    void navigate({
      to: getRememberedProjectPath(projectId) ?? `/projects/${projectId}/${restoreTarget}`,
      replace: true,
    });
  }, [atProjectRoot, workspaceState.isLoading, workspaceState.lastView, navigate, projectId]);

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
