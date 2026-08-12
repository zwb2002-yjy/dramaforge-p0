import { Link, createRoute } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { CreativeStage } from "../features/director/CreativeStage";
import { ProductionStage } from "../features/director/ProductionStage";
import { ShootingStage } from "../features/director/ShootingStage";
import { TrialStage } from "../features/director/TrialStage";
import {
  commandKey,
  confirmDirectorChange,
  proposeDirectorChange,
} from "../features/director/api";
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
  StoryCorePayload,
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

function LockedCreativeChangePanel({
  projectId,
  snapshot,
  refresh,
  onMessage,
  onError,
}: {
  projectId: string;
  snapshot: DirectorWorkspaceSnapshot;
  refresh: () => Promise<unknown>;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
}) {
  const story = snapshot.current_artifacts.story_core;
  const payload = story?.payload as StoryCorePayload | undefined;
  const [theme, setTheme] = useState(payload?.theme ?? "");
  const [coreConflict, setCoreConflict] = useState(payload?.core_conflict ?? "");
  const [emotionalDirection, setEmotionalDirection] = useState(payload?.emotional_direction ?? "");
  const [ending, setEnding] = useState(payload?.ending ?? "");
  const pending = snapshot.pending_changes;

  useEffect(() => {
    if (!payload || pending.length > 0) return;
    setTheme(payload.theme);
    setCoreConflict(payload.core_conflict);
    setEmotionalDirection(payload.emotional_direction);
    setEnding(payload.ending);
  }, [payload, pending.length]);

  const propose = useMutation({
    mutationFn: () => {
      if (!payload) throw new Error("当前没有可修改的创作方案");
      return proposeDirectorChange(projectId, {
        idempotency_key: commandKey("locked-story-change"),
        target_artifact_kind: "story_core",
        summary: "调整故事内核：主题、冲突、情绪走向或结局",
        replacement_payload: {
          ...payload,
          theme: theme.trim(),
          core_conflict: coreConflict.trim(),
          emotional_direction: emotionalDirection.trim(),
          ending: ending.trim(),
        },
      });
    },
    onSuccess: async () => {
      onMessage("变更预览已生成；确认前不会修改锁定版本或创建媒体任务。");
      await refresh();
    },
    onError: (error) => onError(error instanceof Error ? error.message : String(error)),
  });
  const confirm = useMutation({
    mutationFn: (proposalId: string) => confirmDirectorChange(projectId, proposalId),
    onSuccess: async () => {
      onMessage("新版本已确认。相关后续方案已标记为需要重新确认。");
      await refresh();
    },
    onError: (error) => onError(error instanceof Error ? error.message : String(error)),
  });
  const canPropose = snapshot.allowed_actions.includes("propose_change")
    && Boolean(payload)
    && !propose.isPending
    && !confirm.isPending
    && Boolean(theme.trim() && coreConflict.trim() && emotionalDirection.trim() && ending.trim());

  if (
    (!snapshot.allowed_actions.includes("propose_change") && pending.length === 0)
    || !payload
  ) return null;
  return (
    <section className="panel director-change-panel" data-testid="locked-creative-change">
      <div className="panel-header"><div><span className="director-stage-kicker">锁定内容修改</span><h3>先预览，再确认</h3></div></div>
      {pending.length === 0 ? (
        <>
          <p className="muted">调整会先生成不可变的变更预览，列出会失效的后续版本；确认前不会替换当前故事，也不会产生媒体费用。</p>
          <div className="form-grid">
            <label>主题<input value={theme} onChange={(event) => setTheme(event.target.value)} /></label>
            <label>核心冲突<textarea value={coreConflict} onChange={(event) => setCoreConflict(event.target.value)} rows={2} /></label>
            <label>情绪走向<input value={emotionalDirection} onChange={(event) => setEmotionalDirection(event.target.value)} /></label>
            <label>结局落点<textarea value={ending} onChange={(event) => setEnding(event.target.value)} rows={2} /></label>
          </div>
          <button type="button" className="primary" data-testid="propose-locked-creative-change" disabled={!canPropose} onClick={() => propose.mutate()}>
            {propose.isPending ? "正在生成变更预览…" : "查看修改影响"}
          </button>
        </>
      ) : pending.map((change) => (
        <article className="director-change-preview" data-testid={`change-preview-${change.proposal.id}`} key={change.proposal.id}>
          <h4>变更预览</h4>
          <p>{change.proposal.summary}</p>
          <dl className="creative-summary">
            <dt>将替换</dt><dd>当前锁定的 {change.proposal.target_artifact_kind}</dd>
            <dt>失效版本</dt><dd>{change.impact.invalidated_version_ids.length ? `${change.impact.invalidated_version_ids.length} 个后续版本` : "无"}</dd>
            <dt>受影响镜头</dt><dd>{change.impact.affected_shot_ids.length ? change.impact.affected_shot_ids.join("、") : "尚未物化镜头"}</dd>
            <dt>新增费用</dt><dd>{change.impact.estimated_added_cost ?? "待重新生成选模方案后计算"}</dd>
          </dl>
          <button type="button" className="accent" data-testid={`confirm-change-${change.proposal.id}`} disabled={confirm.isPending} onClick={() => confirm.mutate(change.proposal.id)}>
            {confirm.isPending ? "正在确认新版本…" : "确认这项修改"}
          </button>
        </article>
      ))}
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
          <LockedCreativeChangePanel
            projectId={projectId}
            snapshot={snapshot}
            refresh={workspace.refresh}
            onMessage={(value) => { setError(null); setMessage(value); }}
            onError={(value) => { setMessage(null); setError(value); }}
          />
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
