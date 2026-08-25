import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, createRoute, useRouterState } from "@tanstack/react-router";

import { ModelProfileSettings } from "../components/provider/ModelProfileSettings";
import { ProjectWorkspaceShell } from "../features/creation-preview/ProjectWorkspaceShell";
import type { PreviewStage } from "../features/creation-preview/types";
import {
  DIRECTOR_STAGES,
  WORKFLOW_STATUS_ZH,
  stageForStatus,
  stageState,
} from "../features/director/stageMap";
import { fetchDirectorWorkspace } from "../features/director/api";
import type { DirectorWorkspaceSnapshot } from "../features/director/types";
import { ApiError, getSelectedWorkspaceId } from "../lib/api";
import { rootRoute } from "./__root";

export const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectLayout,
});

function workspaceStages(snapshot: DirectorWorkspaceSnapshot | undefined): PreviewStage[] {
  if (!snapshot) {
    return DIRECTOR_STAGES.map((stage, index) => ({
      id: stage.id,
      label: stage.title,
      caption: stage.confirmation,
      state: index === 0 ? "active" : "upcoming",
    }));
  }
  const current = stageForStatus(snapshot.workflow.status);
  return DIRECTOR_STAGES.map((stage) => {
    const state = stageState(stage.id, current, snapshot.workflow.status);
    return {
      id: stage.id,
      label: stage.title,
      caption: stage.confirmation,
      state: state === "done" ? "done" : state === "active" ? "active" : "upcoming",
    };
  });
}

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
        <dt>画幅</dt><dd>{snapshot.aspect_ratio}</dd>
        <dt>锁定版本</dt><dd>{Object.keys(snapshot.current_artifacts).length}</dd>
        <dt>运行批次</dt><dd>{runningBatches.length}</dd>
        <dt>待处理问题</dt><dd>{snapshot.issues.filter((item) => item.status !== "resolved").length}</dd>
      </dl>
      <section>
        <h4>执行边界</h4>
        <p className="muted">专业工作台共享 Workflow、Production Graph、NodeRun 和 Artifact；模型供应商负责价格与结算。</p>
      </section>
    </div>
  );
}

function ProjectOverview({ snapshot }: { snapshot: DirectorWorkspaceSnapshot | undefined }) {
  const { projectId } = projectRoute.useParams();
  const currentStage = snapshot ? stageForStatus(snapshot.workflow.status) : "creative";
  const stage = DIRECTOR_STAGES.find((item) => item.id === currentStage);
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
          <strong>{stage ? `阶段 ${stage.number} · ${stage.title}` : "正在读取"}</strong>
          <p>{snapshot ? WORKFLOW_STATUS_ZH[snapshot.workflow.status] : "正在恢复项目事实"}</p>
        </div>
        <div>
          <small>下一步</small>
          <p>{snapshot?.next_action ?? "打开专业工作台，继续当前导演流程。"}</p>
        </div>
        <Link className="qc-overview-primary" to="/projects/$projectId/production" params={{ projectId }}>
          继续专业制作
        </Link>
      </section>
      <section className="qc-overview-grid">
        <article>
          <span className="director-stage-kicker">快速模式</span>
          <h2>AI 导演工作区</h2>
          <p>完成四阶段、四次硬确认、试拍验收和正式生产授权。</p>
          <Link to="/projects/$projectId/production" params={{ projectId }}>进入快速创作</Link>
        </article>
        <article>
          <span className="director-stage-kicker">专业模式</span>
          <h2>逐镜生产证据</h2>
          <p>展开 Production Graph、NodeRun、ProviderOperation、Artifact 和局部修复范围。</p>
          <Link to="/projects/$projectId/production" params={{ projectId }}>进入专业生产</Link>
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
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const onQuick = pathname.includes("/quick");
  const onProduction = pathname.includes("/production");
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
    enabled: projectId !== "demo" && !onQuick && !onProduction,
    refetchInterval: (query) => {
      const status = query.state.data?.workflow.status;
      return status && ["trial_running", "production_running", "assembling"].includes(status)
        ? 2_500
        : false;
    },
  });

  if (onQuick) return <Outlet />;

  const snapshot = workspace.data ?? undefined;
  return (
    <ProjectWorkspaceShell
      projectId={projectId}
      projectName={snapshot?.project_name ?? (projectId === "demo" ? "演示项目" : "短剧项目")}
      activeView={onProduction ? "production" : "overview"}
      stages={workspaceStages(snapshot)}
      inspector={<EvidenceInspector snapshot={snapshot} />}
      modeLabel={onProduction ? "专业模式" : "项目总览"}
    >
      {workspace.isError && (
        <div className="flash err">无法读取 Director 项目事实：{workspace.error instanceof Error ? workspace.error.message : "未知错误"}</div>
      )}
      {onProduction ? <Outlet /> : <ProjectOverview snapshot={snapshot} />}
    </ProjectWorkspaceShell>
  );
}


