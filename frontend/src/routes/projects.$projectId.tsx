import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, Outlet, createRoute, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { ModelProfileSettings } from "../components/provider/ModelProfileSettings";
import { ProjectWorkspaceShell } from "../components/workstation/ProjectWorkspaceShell";
import { useProjectWorkspaceState, workspaceViewFromPath } from "../hooks/useProjectWorkspaceState";
import { ApiError, fetchProject, getSelectedWorkspaceId, type ProjectRead } from "../lib/api";
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
        <p>项目、场景、镜头与生产证据来自同一 canonical 数据源。</p>
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
        <h4>执行边界</h4>
        <p className="muted">
          专业工作台共享 Workflow、Production Graph、NodeRun 和 Artifact；模型供应商负责价格与结算。
        </p>
      </section>
    </div>
  );
}

function ProjectOverview({ project }: { project: ProjectRead | undefined }) {
  const { projectId } = projectRoute.useParams();
  const { lastView } = useProjectWorkspaceState(projectId);
  const restoreTarget = lastView ?? "scenes";
  return (
    <div data-testid="project-panel" className="qc-project-overview">
      <header className="qc-page-heading">
        <p>项目总览</p>
        <h1>{project?.name ?? "短剧项目"}</h1>
        <span>从场景和镜头到完整交付，画布、版本和媒体证据保留在同一个项目中。</span>
      </header>
      <section className="qc-overview-band">
        <div>
          <small>当前阶段</small>
          <strong>专业制作</strong>
          <p>{project?.stage ?? "正在恢复项目事实"}</p>
        </div>
        <div>
          <small>继续上次查看</small>
          <p>{lastView ? `回到 ${lastView} 视图` : "首次进入项目，默认进入场景总览。"}</p>
        </div>
        <Link
          className="qc-overview-primary"
          to={`/projects/$projectId/${restoreTarget}`}
          params={{ projectId }}
        >
          {lastView ? "继续上次查看" : "进入场景总览"}
        </Link>
      </section>
      <section className="qc-overview-grid">
        <article>
          <span className="director-stage-kicker">导演助手（兼容事实）</span>
          <h2>受控导演建议</h2>
          <p>历史导演流程事实继续保留，但新的创作入口统一在专业工作台。</p>
          <Link to="/projects/$projectId/production" params={{ projectId }}>
            进入专业工作台
          </Link>
        </article>
        <article>
          <span className="director-stage-kicker">专业模式</span>
          <h2>逐镜生产证据</h2>
          <p>展开 Production Graph、NodeRun、ProviderOperation、Artifact 和局部修复范围。</p>
          <Link to="/projects/$projectId/production" params={{ projectId }}>
            进入专业生产
          </Link>
        </article>
      </section>
      <section id="model-settings" className="qc-settings-band">
        <ModelProfileSettings projectId={projectId} workspaceId={getSelectedWorkspaceId()} />
      </section>
    </div>
  );
}

function ProjectLayout() {
  const { projectId } = projectRoute.useParams();
  const location = useRouterState({ select: (state) => state.location });
  const pathname = location.pathname;
  const onQuick = pathname.includes("/quick");
  const view = workspaceViewFromPath(pathname);
  const atRoot = view === null && !onQuick;
  const ws = useProjectWorkspaceState(projectId);
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: async () => {
      try {
        return await fetchProject(projectId);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: projectId !== "demo" && !onQuick && atRoot,
  });

  // Remember the current professional view so the next visit restores it.
  const lastRemembered = useRef<string | null>(null);
  useEffect(() => {
    if (view && lastRemembered.current !== view) {
      lastRemembered.current = view;
      ws.rememberLastView(view);
    }
  }, [view, ws]);

  if (onQuick) return <Outlet />;

  const projectRead = project.data ?? undefined;

  // Project root restores the last professional view unless the user explicitly
  // requested an anchor (e.g. model settings via #model-settings).
  if (atRoot && ws.lastView && !location.hash) {
    return <Navigate to={`/projects/$projectId/${ws.lastView}`} params={{ projectId }} replace />;
  }

  return (
    <ProjectWorkspaceShell
      projectId={projectId}
      projectName={projectRead?.name ?? (projectId === "demo" ? "演示项目" : "短剧项目")}
      activeView={view ?? "overview"}
      inspector={<EvidenceInspector project={projectRead} />}
      modeLabel={view === "production" ? "专业模式" : (view ?? "项目总览")}
    >
      {project.isError && (
        <div className="flash err">
          无法读取项目事实：
          {project.error instanceof Error ? project.error.message : "未知错误"}
        </div>
      )}
      {atRoot ? <ProjectOverview project={projectRead} /> : <Outlet />}
    </ProjectWorkspaceShell>
  );
}
