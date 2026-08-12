import { Link, createRoute } from "@tanstack/react-router";
import { useState } from "react";

import { CreativeStage } from "../features/director/CreativeStage";
import { ProductionStage } from "../features/director/ProductionStage";
import { ShootingStage } from "../features/director/ShootingStage";
import { TrialStage } from "../features/director/TrialStage";
import {
  ACTION_ZH,
  DIRECTOR_STAGES,
  NEXT_ACTION_ZH,
  WORKFLOW_STATUS_ZH,
  stageForStatus,
  stageState,
} from "../features/director/stageMap";
import type {
  DirectorArtifactKind,
  DirectorWorkspaceSnapshot,
} from "../features/director/types";
import { useDirectorWorkspace } from "../features/director/useDirectorWorkspace";
import { projectRoute } from "./projects.$projectId";

export const projectQuickRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/quick",
  component: QuickModePage,
});

const STAGE_ARTIFACTS: Record<string, Array<{ kind: DirectorArtifactKind; label: string }>> = {
  shooting: [
    { kind: "character_bible", label: "人物方案" },
    { kind: "visual_bible", label: "视觉与角色锚点" },
    { kind: "voice_bible", label: "声音方案" },
    { kind: "storyboard_plan", label: "分镜方案" },
    { kind: "risk_report", label: "风险预审" },
    { kind: "selection_plan", label: "推荐模型方案" },
    { kind: "cost_estimate", label: "成本预估" },
  ],
  trial: [
    { kind: "trial_plan", label: "代表镜头计划" },
    { kind: "trial_review", label: "试拍验收" },
    { kind: "quality_report", label: "质量证据" },
  ],
  production: [
    { kind: "quality_report", label: "成片质量报告" },
    { kind: "production_review", label: "逐镜验收" },
    { kind: "repair_plan", label: "局部修复方案" },
  ],
};

function StageRail({ snapshot }: { snapshot: DirectorWorkspaceSnapshot }) {
  const current = stageForStatus(snapshot.workflow.status);
  return (
    <ol className="workflow-steps director-stage-rail" data-testid="director-stage-rail">
      {DIRECTOR_STAGES.map((stage) => {
        const state = stageState(stage.id, current, snapshot.workflow.status);
        return (
          <li key={stage.id} className={state === "pending" ? "" : state}>
            <span>{stage.number}</span>
            <div><strong>{stage.title}</strong><small>{stage.confirmation}</small></div>
          </li>
        );
      })}
    </ol>
  );
}

function ArtifactSummary({
  snapshot,
  stage,
}: {
  snapshot: DirectorWorkspaceSnapshot;
  stage: "shooting" | "trial" | "production";
}) {
  const expected = STAGE_ARTIFACTS[stage] ?? [];
  return (
    <div className="director-output-summary" data-testid={`${stage}-summary`}>
      {expected.map(({ kind, label }) => {
        const artifact = snapshot.current_artifacts[kind];
        return (
          <article key={kind} className={artifact ? "ready" : "pending"}>
            <span>{artifact ? "✓" : "○"}</span>
            <div><strong>{label}</strong><small>{artifact ? `第 ${artifact.revision_no} 版 · ${artifact.status}` : "等待 AI 导演生成"}</small></div>
          </article>
        );
      })}
    </div>
  );
}

function FutureStage({
  snapshot,
  stage,
}: {
  snapshot: DirectorWorkspaceSnapshot;
  stage: "shooting" | "trial" | "production";
}) {
  const definition = DIRECTOR_STAGES.find((candidate) => candidate.id === stage)!;
  const current = stageForStatus(snapshot.workflow.status);
  const state = stageState(stage, current, snapshot.workflow.status);
  const isCurrent = state === "active";
  const actions = snapshot.allowed_actions.map((action) => ACTION_ZH[action] ?? action);
  const descriptions = {
    shooting: "AI 导演会汇总人物形象、声音、动态分镜、翻车风险、模型选择和成本预期；这里不产生图片或视频费用。",
    trial: "先授权明确的预算上限，只生成最能暴露人物、口型与表演风险的代表镜头，再决定是否继续。",
    production: "试拍通过并授权正式预算后才会生产全部镜头；失败时只修受影响的局部，并保留可复用资产。",
  };
  return (
    <section className={`panel director-future-stage ${isCurrent ? "active" : ""}`}>
      <div className="panel-header">
        <div><span className="director-stage-kicker">阶段 {definition.number}</span><h2>{definition.title}</h2></div>
        <strong className={isCurrent ? "status-pending" : state === "done" ? "status-ok" : "muted"}>
          {isCurrent ? WORKFLOW_STATUS_ZH[snapshot.workflow.status] : state === "done" ? "已完成并锁定" : "将在上一步确认后开放"}
        </strong>
      </div>
      <p>{descriptions[stage]}</p>
      <ArtifactSummary snapshot={snapshot} stage={stage} />
      {isCurrent && actions.length > 0 && (
        <div className="callout"><strong>当前可以：</strong> {actions.join(" · ")}</div>
      )}
      {stage === "production" && (
        <Link to="/projects/$projectId/production" params={{ projectId: snapshot.project_id }}>
          查看专业生产板
        </Link>
      )}
    </section>
  );
}

function CreativeLockedSummary({ snapshot }: { snapshot: DirectorWorkspaceSnapshot }) {
  const story = snapshot.current_artifacts.story_core;
  const script = snapshot.current_artifacts.episode_script;
  if (!story || !script) return null;
  const storyPayload = story.payload;
  const scriptPayload = script.payload;
  return (
    <section className="panel director-locked-summary" data-testid="creative-locked-summary">
      <div className="panel-header"><div><span className="director-stage-kicker">阶段 1 · 已确认</span><h2>{String(scriptPayload.title ?? "创作方案")}</h2></div><span className="status-ok">已锁定</span></div>
      <dl className="creative-summary">
        <dt>主题</dt><dd>{String(storyPayload.theme ?? "—")}</dd>
        <dt>核心冲突</dt><dd>{String(storyPayload.core_conflict ?? "—")}</dd>
        <dt>结局</dt><dd>{String(storyPayload.ending ?? "—")}</dd>
        <dt>目标时长</dt><dd>{String(scriptPayload.target_duration_seconds ?? "—")} 秒</dd>
      </dl>
      <p className="muted">若要修改已锁定内容，AI 导演必须先生成变更预览，展示失效范围与新增成本。</p>
    </section>
  );
}

function DirectorSidebar({ snapshot }: { snapshot: DirectorWorkspaceSnapshot }) {
  const activeBudget = snapshot.budget_authorizations.filter((item) => item.status === "active");
  return (
    <aside className="director-sidebar" data-testid="director-sidebar">
      <section className="panel">
        <span className="director-stage-kicker">AI 导演</span>
        <h3>{WORKFLOW_STATUS_ZH[snapshot.workflow.status]}</h3>
        <p>{NEXT_ACTION_ZH[snapshot.workflow.status]}</p>
        <div className="director-next-actions">
          {snapshot.allowed_actions.map((action) => <span key={action}>{ACTION_ZH[action] ?? action}</span>)}
          {snapshot.allowed_actions.length === 0 && <span>当前没有可执行动作</span>}
        </div>
      </section>
      <section className="panel">
        <h3>项目约束</h3>
        <dl className="creative-summary">
          <dt>模板</dt><dd>真人写实 · 角色对白</dd>
          <dt>时长</dt><dd>15–30 秒</dd>
          <dt>画幅</dt><dd>{snapshot.aspect_ratio}</dd>
          <dt>版本</dt><dd>{snapshot.workflow.template_version}</dd>
        </dl>
      </section>
      <section className="panel">
        <h3>风险与预算</h3>
        <p>{snapshot.issues.length ? `${snapshot.issues.length} 个问题需要处理` : "暂未发现阻断问题"}</p>
        <p>{activeBudget.length ? `${activeBudget.length} 笔有效授权` : "尚未授权任何媒体预算"}</p>
      </section>
    </aside>
  );
}

function QuickModePage() {
  const { projectId } = projectQuickRoute.useParams();
  const workspace = useDirectorWorkspace(projectId);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (projectId === "demo") {
    return <div className="panel"><h2>AI 导演工作台</h2><p>请先从项目大厅创建真实项目。</p></div>;
  }
  if (workspace.isLoading) {
    return <div className="panel" data-testid="director-loading"><h2>AI 导演正在读取项目…</h2><p className="muted">正在恢复阶段、锁定版本、预算和质量证据。</p></div>;
  }
  if (workspace.isError || !workspace.data) {
    return <div className="panel"><h2>暂时无法打开 AI 导演工作台</h2><p className="status-bad">{workspace.error instanceof Error ? workspace.error.message : "未知错误"}</p><button type="button" onClick={() => workspace.refetch()}>重试</button></div>;
  }

  const snapshot = workspace.data;
  const currentStage = stageForStatus(snapshot.workflow.status);
  return (
    <div data-testid="quick-mode" className="director-workspace">
      <div className="page-title-row">
        <div><h1>AI 导演工作台</h1><p className="muted">{snapshot.project_name} · 你决定作品内核，AI 带你完成拍摄与交付</p></div>
        <span className="director-status-chip">{WORKFLOW_STATUS_ZH[snapshot.workflow.status]}</span>
      </div>
      <StageRail snapshot={snapshot} />
      {message && <div className="flash ok" data-testid="director-message">{message}</div>}
      {error && <div className="flash err" data-testid="director-error">{error}</div>}
      {snapshot.pending_changes.length > 0 && (
        <div className="callout warn" data-testid="pending-change">有 {snapshot.pending_changes.length} 个变更预览等待确认；系统尚未应用这些修改。</div>
      )}
      <div className="director-layout">
        <main>
          {currentStage === "creative" ? (
            <CreativeStage projectId={projectId} snapshot={snapshot} refresh={workspace.refresh} onMessage={(value) => { setError(null); setMessage(value); }} onError={(value) => { setMessage(null); setError(value); }} />
          ) : (
            <CreativeLockedSummary snapshot={snapshot} />
          )}
          {currentStage === "shooting" ? (
            <ShootingStage projectId={projectId} snapshot={snapshot} refresh={workspace.refresh} onMessage={(value) => { setError(null); setMessage(value); }} onError={(value) => { setMessage(null); setError(value); }} />
          ) : (
            <FutureStage snapshot={snapshot} stage="shooting" />
          )}
          {currentStage === "trial" ? (
            <TrialStage projectId={projectId} snapshot={snapshot} refresh={workspace.refresh} onMessage={(value) => { setError(null); setMessage(value); }} onError={(value) => { setMessage(null); setError(value); }} />
          ) : (
            <FutureStage snapshot={snapshot} stage="trial" />
          )}
          {currentStage === "production" ? (
            <ProductionStage projectId={projectId} snapshot={snapshot} refresh={workspace.refresh} onMessage={(value) => { setError(null); setMessage(value); }} onError={(value) => { setMessage(null); setError(value); }} />
          ) : (
            <FutureStage snapshot={snapshot} stage="production" />
          )}
        </main>
        <DirectorSidebar snapshot={snapshot} />
      </div>
    </div>
  );
}
