import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, Outlet, createRoute, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { ModelProfileSettings } from "../components/provider/ModelProfileSettings";
import { ProjectWorkspaceShell } from "../components/workstation/ProjectWorkspaceShell";
import { WORKFLOW_STATUS_ZH, stageForStatus } from "../features/director/stageMap";
import { fetchDirectorWorkspace } from "../features/director/api";
import type { DirectorWorkspaceSnapshot } from "../features/director/types";
import { useProjectWorkspaceState, workspaceViewFromPath } from "../hooks/useProjectWorkspaceState";
import { ApiError, getSelectedWorkspaceId } from "../lib/api";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function EvidenceInspector({ snapshot }: { snapshot: DirectorWorkspaceSnapshot | undefined }) {
  if (!snapshot) return <p className="muted">正在读取画布、版本与生产证据。</p>;
  const runningBatches = snapshot.production_batches.filter((item) => item.status === "running");
  return (
    <div className="qc-project-inspector-summary">
      <section>
        <span className="director-stage-kicker">当前状态</span>
        <h3>{WORKFLOW_STATUS_ZH[snapshot.workflow.status]}</h3>
        <p>{snapshot.next_action}</p>
      </section>
      <dl>
        <dt>画幅</dt>
        <dd>{snapshot.aspect_ratio}</dd>
        <dt>锁定版本</dt>
        <dd>{Object.keys(snapshot.current_artifacts).length}</dd>
        <dt>运行批次</dt>
        <dd>{runningBatches.length}</dd>
        <dt>待处理问题</dt>
        <dd>{snapshot.issues.filter((item) => item.status !== "resolved").length}</dd>
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

function ProjectOverview({ snapshot }: { snapshot: DirectorWorkspaceSnapshot | undefined }) {
  const { projectId } = projectRoute.useParams();
  const { lastView } = useProjectWorkspaceState(projectId);
  const currentStage = snapshot ? stageForStatus(snapshot.workflow.status) : "creative";
  const restoreTarget = lastView ?? "scenes";
  return (
    <div data-testid="project-panel" className="qc-project-overview">
      <header className="qc-page-heading">
        <p>项目总览</p>
        <h1>{snapshot?.project_name ?? "短剧项目"}</h1>
        <span>从场景和镜头到完整交付，画布、版本和媒体证据保留在同一个项目中。</span>
      </header>
      <section className="qc-overview-band">
        <div>
          <small>当前阶段</small>
          <strong>{currentStage === "creative" ? "专业制作" : "专业制作"}</strong>
          <p>{snapshot ? WORKFLOW_STATUS_ZH[snapshot.workflow.status] : "正在恢复项目事实"}</p>
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
  const workspace = useQuery({
    queryKey: ["director-workspace", projectId],
    queryFn: async () => {
      try {
        return await fetchDirectorWorkspace(projectId);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    // The professional workbench is the primary product surface. It reads its
    // own Project/Shot/Graph facts and must not probe the retired Director
    // snapshot (which would create a noisy 404 for projects without a legacy
    // workflow). The legacy overview may still use the snapshot when opened.
    enabled: projectId !== "demo" && !onQuick && atRoot,
    refetchInterval: (query) => {
      const status = query.state.data?.workflow.status;
      return status && ["trial_running", "production_running", "assembling"].includes(status)
        ? 2_500
        : false;
    },
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

  const snapshot = workspace.data ?? undefined;

  // Project root restores the last professional view unless the user explicitly
  // requested an anchor (e.g. model settings via #model-settings).
  if (atRoot && ws.lastView && !location.hash) {
    return <Navigate to={`/projects/$projectId/${ws.lastView}`} params={{ projectId }} replace />;
  }

  return (
    <ProjectWorkspaceShell
      projectId={projectId}
      projectName={snapshot?.project_name ?? (projectId === "demo" ? "演示项目" : "短剧项目")}
      activeView={view ?? "overview"}
      inspector={<EvidenceInspector snapshot={snapshot} />}
      modeLabel={view === "production" ? "专业模式" : (view ?? "项目总览")}
    >
      {workspace.isError && (
        <div className="flash err">
          无法读取 Director 项目事实：
          {workspace.error instanceof Error ? workspace.error.message : "未知错误"}
        </div>
      )}
      {atRoot ? <ProjectOverview snapshot={snapshot} /> : <Outlet />}
    </ProjectWorkspaceShell>
  );
}
