import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ArtifactStage } from "../../lib/artifactStage";
import { fetchSnapshot } from "../../lib/api";
import { imageArtifacts, latestImageArtifact } from "../../lib/projectMedia";
import { zhErrorSummary, zhNode, zhStatus } from "../../lib/zh";
import {
  approveDirectorStage,
  authorizeDirectorBudget,
  commandKey,
  inspectTrial,
  materializeTrial,
  reviewTrial,
} from "./api";
import { areTrialRunsTerminal, isTrialPricingReady } from "./safetyGates";
import type {
  CostEstimatePayload,
  DirectorWorkspaceSnapshot,
  QualityDimension,
  QualityReportPayload,
  TrialPlanPayload,
  TrialReviewPayload,
} from "./types";
import { artifactPayload } from "./types";

type TrialStageProps = {
  projectId: string;
  snapshot: DirectorWorkspaceSnapshot;
  refresh: () => Promise<unknown>;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
};

const QUALITY_ZH: Record<QualityDimension, string> = {
  request_contract: "有效请求完整性",
  identity: "人物身份与外观",
  technical_integrity: "技术完整性与恶性崩坏",
  voice_assignment: "声线归属与稳定",
  mouth_motion: "嘴巴开合与时序",
  continuity: "镜头内连续性",
  narrative_and_performance: "叙事、表演与审美",
};

const STATUS_ZH: Record<string, string> = {
  passed: "通过",
  warning: "有警告",
  needs_human: "需要你查看",
  blocked: "阻断",
  not_applicable: "不适用",
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function activeTrialBatch(snapshot: DirectorWorkspaceSnapshot) {
  return [...snapshot.production_batches]
    .reverse()
    .find((batch) => batch.batch_kind === "trial") ?? null;
}

function formatMoney(value: string | null, currency: string): string {
  return value === null ? "价格尚未验证" : `${value} ${currency}`;
}

function BudgetAuthorizationPanel({
  projectId,
  snapshot,
  cost,
  refresh,
  onMessage,
  onError,
}: TrialStageProps & { cost: CostEstimatePayload }) {
  const [limit, setLimit] = useState(cost.trial_total ?? "");
  const [acknowledged, setAcknowledged] = useState(false);
  const pricingReady = isTrialPricingReady(cost);
  const parsedLimit = Number(limit);
  const estimate = Number(cost.trial_total ?? 0);
  const limitReady = Number.isFinite(parsedLimit) && parsedLimit > 0 && parsedLimit >= estimate;
  const mutation = useMutation({
    mutationFn: async () => {
      const reusableAuthorization = snapshot.budget_authorizations.find(
        (item) =>
          item.authorization_kind === "trial_budget" &&
          item.status === "active" &&
          item.pricing_snapshot_id === cost.pricing_snapshot_id &&
          item.currency === cost.currency &&
          Number(item.limit_amount) === parsedLimit,
      );
      const authorization = reusableAuthorization ?? await authorizeDirectorBudget(projectId, {
          authorization_kind: "trial_budget",
          idempotency_key: commandKey("trial-budget"),
          pricing_snapshot_id: cost.pricing_snapshot_id,
          limit_amount: limit,
          currency: cost.currency,
          expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
        });
      await approveDirectorStage(
        projectId,
        "trial_budget",
        commandKey("approve-trial-budget"),
        authorization.id,
      );
      return authorization;
    },
    onSuccess: async () => {
      onMessage("试拍预算已授权。系统仍未开始生成，需由你再点击“开始代表镜头试拍”。");
      await refresh();
    },
    onError: (error) => onError(errorText(error)),
  });
  return (
    <section className="panel director-budget-panel" data-testid="trial-budget-panel">
      <div className="panel-header"><div><h3>硬确认 3 / 4 · 试拍预算授权</h3><p className="muted">第一次产生图片、视频或声音费用前的硬门槛</p></div></div>
      <div className="status-grid">
        <div className="status-card"><span className="status-label">价格快照</span><strong>{cost.pricing_snapshot_id}</strong></div>
        <div className="status-card"><span className="status-label">代表镜头估算</span><strong>{formatMoney(cost.trial_total, cost.currency)}</strong></div>
        <div className="status-card"><span className="status-label">授权有效期</span><strong>1 小时</strong></div>
      </div>
      <ul className="dense">{cost.trial.map((line) => <li key={line.purpose}><span>{line.purpose} × {line.quantity}</span><strong>{formatMoney(line.estimated_amount, line.currency)}</strong></li>)}</ul>
      {!pricingReady && <div className="callout warn">供应商价格尚未形成可验证快照。为了避免未知费用，系统会继续阻止试拍授权和媒体请求。</div>}
      <label>本次试拍最高预算（{cost.currency}）<input type="number" min="0" step="0.01" value={limit} onChange={(event) => setLimit(event.target.value)} /></label>
      <label className="director-rights-confirm"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我已看过代表镜头、价格快照和已知风险，同意在不超过此上限的范围内试拍一次</span></label>
      <button type="button" className="accent" disabled={!pricingReady || !limitReady || !acknowledged || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "正在记录授权…" : "确认并授权试拍预算"}</button>
      {pricingReady && !limitReady && limit && <p className="status-bad">最高预算不能低于当前试拍估算。</p>}
    </section>
  );
}

function TrialProgress({
  projectId,
  snapshot,
  refresh,
  onMessage,
  onError,
}: TrialStageProps) {
  const queryClient = useQueryClient();
  const batch = activeTrialBatch(snapshot);
  const project = useQuery({
    queryKey: ["snapshot", projectId],
    queryFn: () => fetchSnapshot(projectId),
    refetchInterval: 2_500,
  });
  const trialRuns = useMemo(
    () => (project.data?.node_runs ?? []).filter((run) => String(run.input_snapshot.production_batch_id ?? "") === batch?.id),
    [batch?.id, project.data?.node_runs],
  );
  const allTerminal = Boolean(batch && areTrialRunsTerminal(trialRuns.map((run) => run.status)));
  const materialize = useMutation({
    mutationFn: () => materializeTrial(projectId, commandKey("materialize-trial")),
    onSuccess: async (result) => {
      onMessage(`代表镜头已进入生产，共 ${result.node_runs.length} 个受控节点。`);
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: ["snapshot", projectId] })]);
    },
    onError: (error) => onError(errorText(error)),
  });
  const inspect = useMutation({
    mutationFn: () => {
      if (!batch) throw new Error("试拍批次尚未创建");
      return inspectTrial(projectId, batch.id, commandKey("inspect-trial"));
    },
    onSuccess: async () => { onMessage("试拍质检完成。请查看每一项证据后作决定。"); await refresh(); },
    onError: (error) => onError(errorText(error)),
  });
  const trialRunIds = useMemo(() => new Set(trialRuns.map((run) => run.id)), [trialRuns]);
  const images = imageArtifacts(project.data?.artifacts ?? []).filter(
    (artifact) => artifact.produced_by_run_id && trialRunIds.has(artifact.produced_by_run_id),
  );
  return (
    <section className="panel" data-testid="trial-progress">
      <div className="panel-header"><div><h3>代表镜头生产</h3><p className="muted">预算已授权，但只有点击开始后才会创建媒体任务。</p></div><strong>{batch ? batch.status : "尚未开始"}</strong></div>
      {!batch && <button type="button" className="accent" disabled={materialize.isPending} onClick={() => materialize.mutate()}>{materialize.isPending ? "正在创建受控任务…" : "开始代表镜头试拍"}</button>}
      {batch && (
        <>
          <div className="status-grid"><div className="status-card"><span className="status-label">批次</span><strong>{batch.id.slice(0, 8)}…</strong></div><div className="status-card"><span className="status-label">代表镜头</span><strong>{batch.selected_shot_ids.join("、")}</strong></div><div className="status-card"><span className="status-label">节点</span><strong>{trialRuns.length}</strong></div></div>
          <div className="director-trial-run-list">{trialRuns.map((run) => <article key={run.id}><div><strong>{zhNode(run.node_key)}</strong><span>{zhStatus(run.status)}</span></div>{run.error_code && <p className="status-bad">{zhErrorSummary(run.error_code, run.error_summary)}</p>}</article>)}</div>
          {batch.status === "running" && <button type="button" className="primary" disabled={!allTerminal || inspect.isPending} onClick={() => inspect.mutate()}>{inspect.isPending ? "正在汇总证据…" : allTerminal ? "运行已结束，生成质量报告" : "等待所有节点结束"}</button>}
        </>
      )}
      {latestImageArtifact(images) && <ArtifactStage projectId={projectId} stageArt={latestImageArtifact(images)} stageLabel="代表镜头证据" previewArts={images} previewLimit={6} testId="trial-artifact" />}
    </section>
  );
}

function QualityEvidence({ report }: { report: QualityReportPayload }) {
  return (
    <section className="panel" data-testid="trial-quality-report">
      <div className="panel-header"><div><h3>试拍质量证据</h3><p className="muted">自动信号是证据，不替你决定主观质量。</p></div><strong className={report.overall_status === "blocked" ? "status-bad" : report.overall_status === "passed" ? "status-ok" : "status-pending"}>{STATUS_ZH[report.overall_status]}</strong></div>
      <div className="director-quality-grid">{report.dimensions.map((item) => <article key={item.dimension} className={item.status}><header><strong>{QUALITY_ZH[item.dimension]}</strong><span>{STATUS_ZH[item.status]}</span></header><p>{item.summary}</p>{item.evidence_refs.length > 0 && <small>证据：{item.evidence_refs.join(" · ")}</small>}{item.dimension === "identity" && <p className="muted">系统会核对角色参考绑定与产物血缘；人物、发型、服装和跨帧观感由你在试拍中确认。</p>}</article>)}</div>
      {report.hard_blockers.length > 0 && <div className="callout warn"><strong>不可覆盖的硬阻断：</strong><ul>{report.hard_blockers.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {report.limitations.length > 0 && <details><summary>查看自动质检能力边界</summary><ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>}
    </section>
  );
}

function TrialDecision({
  projectId,
  snapshot,
  report,
  refresh,
  onMessage,
  onError,
}: TrialStageProps & { report: QualityReportPayload }) {
  const batch = activeTrialBatch(snapshot);
  const [note, setNote] = useState("");
  const [stopConfirmed, setStopConfirmed] = useState(false);
  const mutation = useMutation({
    mutationFn: (decision: "accept" | "repair" | "stop") => {
      if (!batch) throw new Error("试拍批次不存在");
      return reviewTrial(projectId, { batch_id: batch.id, decision, user_note: note, idempotency_key: commandKey(`trial-${decision}`) });
    },
    onSuccess: async (result) => {
      const payload = result.payload as TrialReviewPayload;
      onMessage(payload.decision === "accept" ? "试拍已验收。正式生产前仍需单独授权完整预算。" : payload.decision === "repair" ? "已记录修复意向。生成修复方案和额外费用前不会自动重试。" : "已停止本次创作，没有新的媒体请求。 ");
      await refresh();
    },
    onError: (error) => onError(errorText(error)),
  });
  const acceptBlocked = report.hard_blockers.length > 0 || report.overall_status === "blocked";
  const overrideReasonRequired = ["warning", "needs_human"].includes(report.overall_status);
  const acceptDisabled = acceptBlocked || (overrideReasonRequired && !note.trim());
  return (
    <section className="panel director-hard-confirm" data-testid="trial-decision">
      <div><span>试拍验收</span><h3>人物、声线、嘴巴开合、表演和风格是否达到你的底线？</h3><p>接受后也不会立刻生产全片；下一步会再次展示并询问正式预算。</p><label>给 AI 导演的验收说明<textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3} placeholder="指出喜欢、不喜欢和必须修的部分" /></label></div>
      <div className="director-confirm-actions"><button type="button" className="accent" disabled={acceptDisabled || mutation.isPending} onClick={() => mutation.mutate("accept")}>接受试拍质量</button><button type="button" disabled={mutation.isPending} onClick={() => mutation.mutate("repair")}>先生成局部修复方案</button><label className="director-stop-confirm"><input type="checkbox" checked={stopConfirmed} onChange={(event) => setStopConfirmed(event.target.checked)} />确认停止</label><button type="button" className="danger" disabled={!stopConfirmed || mutation.isPending} onClick={() => mutation.mutate("stop")}>停止创作</button></div>
      {acceptBlocked && <p className="status-bad">存在硬阻断，不能用主观验收覆盖；只能修复或停止。</p>}
      {!acceptBlocked && overrideReasonRequired && !note.trim() && <p className="status-pending">接受需要人工判断的质量项前，请写明你的验收理由；系统会保留原自动结果并单独记录本次覆盖。</p>}
    </section>
  );
}

export function TrialStage(props: TrialStageProps) {
  const { snapshot } = props;
  const cost = artifactPayload<CostEstimatePayload>(snapshot, "cost_estimate");
  const trialPlan = artifactPayload<TrialPlanPayload>(snapshot, "trial_plan");
  const quality = artifactPayload<QualityReportPayload>(snapshot, "quality_report");
  const review = artifactPayload<TrialReviewPayload>(snapshot, "trial_review");
  return (
    <section data-testid="trial-stage">
      <section className="panel director-stage-intro"><div><span className="director-stage-kicker">阶段 3</span><h2>代表镜头试拍</h2></div><p>只用一个高信息量镜头验证人物、声音、口型和表演。预算授权与真正开始试拍是两个独立动作。</p></section>
      {trialPlan && <section className="panel"><h3>代表镜头：{trialPlan.representative_shot_id}</h3><p>{trialPlan.selection_reason}</p><p className="muted">将检查：{trialPlan.quality_dimensions.join(" · ")}</p></section>}
      {snapshot.workflow.status === "awaiting_trial_authorization" && cost && <BudgetAuthorizationPanel {...props} cost={cost} />}
      {snapshot.workflow.status === "awaiting_trial_authorization" && !cost && <div className="callout warn">缺少成本快照，不能授权试拍。</div>}
      {["trial_running", "awaiting_trial_review"].includes(snapshot.workflow.status) && <TrialProgress {...props} />}
      {quality && <QualityEvidence report={quality} />}
      {snapshot.workflow.status === "awaiting_trial_review" && quality && <TrialDecision {...props} report={quality} />}
      {review && <section className="panel"><h3>已记录试拍决定</h3><p>{review.decision === "accept" ? "接受试拍" : review.decision === "repair" ? "请求修复" : "停止创作"}</p>{review.user_note && <p>{review.user_note}</p>}</section>}
    </section>
  );
}
