import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  artifactContentUrl,
  artifactVideoFrameUrl,
  fetchSnapshot,
  type ProjectSnapshot,
} from "../../lib/api";
import {
  audioArtifacts,
  imageArtifacts,
  videoArtifacts,
} from "../../lib/projectMedia";
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
  StoryboardPlanPayload,
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

function isTrialQualityReport(value: unknown): value is QualityReportPayload {
  if (!value || typeof value !== "object") return false;
  const report = value as Partial<QualityReportPayload>;
  return typeof report.logical_shot_id === "string" && Array.isArray(report.dimensions);
}

function compact(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 18 ? `${value.slice(0, 12)}…` : value;
}

function sourceCommit(run: ProjectSnapshot["node_runs"][number] | undefined): string {
  const value = run?.input_snapshot.source_commit;
  return typeof value === "string" && value ? value : "—";
}

function TrialMediaEvidence({
  projectId,
  project,
  trialRuns,
  snapshot,
}: {
  projectId: string;
  project: ProjectSnapshot;
  trialRuns: ProjectSnapshot["node_runs"];
  snapshot: DirectorWorkspaceSnapshot;
}) {
  const runIds = new Set(trialRuns.map((run) => run.id));
  const artifacts = project.artifacts.filter(
    (artifact) => artifact.produced_by_run_id && runIds.has(artifact.produced_by_run_id),
  );
  const runById = new Map(trialRuns.map((run) => [run.id, run]));
  const byNode = (nodeKey: string) => artifacts.find(
    (artifact) => runById.get(artifact.produced_by_run_id ?? "")?.node_key === nodeKey,
  ) ?? null;
  const canonical = byNode("character_reference") ?? imageArtifacts(artifacts)[0] ?? null;
  const keyframe = byNode("keyframe") ?? imageArtifacts(artifacts).find((item) => item.id !== canonical?.id) ?? null;
  const video = byNode("video") ?? videoArtifacts(artifacts)[0] ?? null;
  const voice = byNode("voice") ?? audioArtifacts(artifacts)[0] ?? null;
  const storyboard = artifactPayload<StoryboardPlanPayload>(snapshot, "storyboard_plan");
  const trialPlan = artifactPayload<TrialPlanPayload>(snapshot, "trial_plan");
  const representativeShot = storyboard?.shots.find(
    (shot) => shot.shot_id === trialPlan?.representative_shot_id,
  );
  const operations = (project.provider_operations ?? []).filter(
    (operation) => operation.node_run_id && runIds.has(operation.node_run_id),
  );
  const videoOperation = operations.find(
    (operation) => operation.node_run_id === video?.produced_by_run_id,
  );
  const videoEffective = videoOperation?.request_summary.effective_request as
    | Record<string, unknown>
    | undefined;
  const videoOptions = videoEffective?.common_options as Record<string, unknown> | undefined;

  return (
    <div className="director-trial-evidence" data-testid="trial-media-evidence">
      <section className="director-evidence-media">
        <header>
          <div><h3>真实试拍媒体</h3><p className="muted">角色参考、关键帧、视频和后配音均来自当前试拍批次。</p></div>
          <span>{artifacts.length} 个 Artifact</span>
        </header>
        <div className="director-evidence-visuals">
          <article>
            <span>Canonical</span>
            {canonical ? <img src={artifactContentUrl(projectId, canonical.id)} alt="主角 Canonical" /> : <div className="director-media-empty">等待角色参考</div>}
            {canonical && <small><code>{compact(canonical.id)}</code> · {compact(canonical.content_hash)}</small>}
          </article>
          <article>
            <span>关键帧</span>
            {keyframe ? <img src={artifactContentUrl(projectId, keyframe.id)} alt="代表镜头关键帧" /> : <div className="director-media-empty">等待关键帧</div>}
            {keyframe && <small><code>{compact(keyframe.id)}</code> · {compact(keyframe.content_hash)}</small>}
          </article>
        </div>
        <div className="director-evidence-av">
          <article>
            <div>
              <strong>代表镜头视频</strong>
              <small>
                {video
                  ? `${video.width && video.height ? `${video.width}×${video.height} · ` : ""}${String(videoOptions?.aspect_ratio ?? snapshot.aspect_ratio)} · ${String(videoOptions?.frame_rate ?? "—")} fps · ${String(videoOptions?.num_frames ?? "—")} 帧 · ${video.duration_seconds ?? String(videoOptions?.duration_seconds ?? "—")} 秒`
                  : "等待视频"}
              </small>
            </div>
            {video ? <video controls preload="metadata" src={artifactContentUrl(projectId, video.id)} data-testid="trial-video" /> : <div className="director-media-empty">视频完成后可在此直接播放</div>}
          </article>
          <article>
            <div><strong>对白后配音</strong><small>{representativeShot?.dialogue.map((item) => `${item.speaker}：${item.text}`).join(" / ") || "当前镜头无对白文本"}</small></div>
            {voice ? <audio controls preload="metadata" src={artifactContentUrl(projectId, voice.id)} data-testid="trial-audio" /> : <div className="director-media-empty">音频完成后可在此直接播放</div>}
            <p className="muted">当前模板为 post-dub，不代表已完成 lip-sync；嘴巴开合与语音同步仍需人工判断。</p>
          </article>
        </div>
        {video && (
          <section className="director-frame-evidence" data-testid="trial-video-frames">
            <header><strong>首 / 中 / 末帧</strong><span>从同一视频 Artifact 确定性解码</span></header>
            <div>
              {(["start", "mid", "end"] as const).map((role) => (
                <figure key={role}>
                  <img src={artifactVideoFrameUrl(projectId, video.id, role)} alt={role === "start" ? "视频首帧" : role === "mid" ? "视频中间帧" : "视频末帧"} />
                  <figcaption>{role === "start" ? "首帧" : role === "mid" ? "中间帧" : "末帧"}</figcaption>
                </figure>
              ))}
            </div>
          </section>
        )}
      </section>

      <section className="director-operation-evidence" data-testid="trial-execution-evidence">
        <header><div><h3>执行证据</h3><p className="muted">显示脱敏有效请求、参数翻译、费用状态与不可变血缘。</p></div><span>{operations.length} 次 Unified 操作</span></header>
        {operations.map((operation) => {
          const request = operation.request_summary;
          const effective = request.effective_request as Record<string, unknown> | undefined;
          const translation = request.translation_report as Record<string, unknown> | undefined;
          const response = operation.response_summary;
          const run = operation.node_run_id ? runById.get(operation.node_run_id) : undefined;
          return (
            <article key={operation.id}>
              <div className="director-operation-heading">
                <div><strong>{operation.actual_provider} · {operation.actual_model}</strong><small>{operation.operation_kind} · {operation.status}</small></div>
                <span>{operation.execution_path_version ?? "路径未记录"}</span>
              </div>
              <dl>
                <dt>Provider request</dt><dd><code>{compact(operation.provider_request_id)}</code></dd>
                <dt>ProviderOperation</dt><dd><code>{compact(operation.id)}</code></dd>
                <dt>Binding / Manifest</dt><dd><code>{compact(operation.model_binding_id)}</code> / <code>{compact(operation.capability_manifest_hash)}</code></dd>
                <dt>source commit</dt><dd><code>{compact(sourceCommit(run))}</code></dd>
                <dt>参考 Artifact</dt><dd>{Array.isArray(effective?.reference_artifact_ids) ? effective.reference_artifact_ids.map(String).map(compact).join(" · ") : "—"}</dd>
                <dt>有效参数</dt><dd><code>{JSON.stringify(effective?.common_options ?? {})}</code></dd>
                <dt>参数转换</dt><dd><code>{JSON.stringify(translation?.transformations ?? [])}</code></dd>
                <dt>丢弃参数</dt><dd><code>{JSON.stringify(translation?.dropped_options ?? [])}</code></dd>
                <dt>费用</dt><dd>{operation.provider_cost === null ? "Provider 未报告" : `${operation.provider_cost} ${operation.currency}`} · {String(response.cost_status ?? "not_reported")}</dd>
              </dl>
            </article>
          );
        })}
        {operations.length === 0 && <div className="director-media-empty">媒体 ProviderOperation 尚未产生；授权前这里保持为空。</div>}
      </section>

      <section className="callout warn director-known-limits" data-testid="trial-known-limitations">
        <strong>当前已知限制</strong>
        <ul>
          <li>人物、发型、服装、肢体、遮挡和跨帧观感必须由人查看，系统不使用人脸相似度替你放行。</li>
          <li>视频合同为单首帧 I2V、9:16、24 fps、121 帧、约 5 秒且无原生音频。</li>
          <li>对白采用 post-dub（后配音）；口型、表演和声画关系可能需要局部修复。</li>
        </ul>
      </section>
    </div>
  );
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
    refetchInterval: snapshot.workflow.status === "trial_running" ? 2_500 : false,
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
      {project.data && (
        <TrialMediaEvidence
          projectId={projectId}
          project={project.data}
          trialRuns={trialRuns}
          snapshot={snapshot}
        />
      )}
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
  const qualityRaw = snapshot.current_artifacts.quality_report?.payload;
  const quality = isTrialQualityReport(qualityRaw) ? qualityRaw : null;
  const review = artifactPayload<TrialReviewPayload>(snapshot, "trial_review");
  const hasTrialBatch = snapshot.production_batches.some((batch) => batch.batch_kind === "trial");
  return (
    <section data-testid="trial-stage">
      <section className="panel director-stage-intro"><div><span className="director-stage-kicker">阶段 3</span><h2>代表镜头试拍</h2></div><p>只用一个高信息量镜头验证人物、声音、口型和表演。预算授权与真正开始试拍是两个独立动作。</p></section>
      {trialPlan && <section className="panel"><h3>代表镜头：{trialPlan.representative_shot_id}</h3><p>{trialPlan.selection_reason}</p><p className="muted">将检查：{trialPlan.quality_dimensions.join(" · ")}</p></section>}
      {snapshot.workflow.status === "awaiting_trial_authorization" && cost && <BudgetAuthorizationPanel {...props} cost={cost} />}
      {snapshot.workflow.status === "awaiting_trial_authorization" && !cost && <div className="callout warn">缺少成本快照，不能授权试拍。</div>}
      {(["trial_running", "awaiting_trial_review"].includes(snapshot.workflow.status) || hasTrialBatch) && <TrialProgress {...props} />}
      {quality && <QualityEvidence report={quality} />}
      {snapshot.workflow.status === "awaiting_trial_review" && quality && <TrialDecision {...props} report={quality} />}
      {review && <section className="panel"><h3>已记录试拍决定</h3><p>{review.decision === "accept" ? "接受试拍" : review.decision === "repair" ? "请求修复" : "停止创作"}</p>{review.user_note && <p>{review.user_note}</p>}</section>}
    </section>
  );
}
