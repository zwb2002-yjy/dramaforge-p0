import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet, createRoute, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { ProjectWorkspaceShell } from "../components/workstation/ProjectWorkspaceShell";
import { useProjectWorkspaceState, workspaceViewFromPath } from "../hooks/useProjectWorkspaceState";
import { ApiError, fetchProject, type ProjectRead } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function EvidenceInspector({ project }: { project: ProjectRead | undefined }) {
  if (!project) return <p className="muted">正在读取项目与工作区事实。</p>;
  return (
    <div className="qc-project-inspector-summary">
      <section>
        <span className="director-stage-kicker">当前状态</span>
        <h3>{project.stage}</h3>
        <p>项目、场景、镜头与制作证据来自同一事实源。</p>
      </section>
      <dl>
        <dt>画幅</dt>
        <dd>{project.aspect_ratio}</dd>
        <dt>项目版本</dt>
        <dd>{project.version}</dd>
        <dt>目标平台</dt>
        <dd>{project.target_platform}</dd>
      </dl>
      <section>
        <h4>事实边界</h4>
        <p className="muted">创作工作台共享同一套项目、制作和产物事实。</p>
      </section>
    </div>
  );
}

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
      inspector={view === "scenes" ? undefined : <EvidenceInspector project={projectRead} />}
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
