import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  exportDownloadUrl,
  fetchSnapshot,
  grantExportDownload,
} from "../../lib/api";
import {
  approveDirectorStage,
  authorizeAndMaterializeRepair,
  authorizeDirectorBudget,
  commandKey,
  exportProduction,
  inspectProduction,
  materializeProduction,
  planRepairs,
  resumePreSubmitRepair,
  reviewProduction,
} from "./api";
import { areTrialRunsTerminal, isProductionPricingReady } from "./safetyGates";
import { TrialMediaEvidence } from "./TrialStage";
import { artifactPayload } from "./types";
import type {
  CostEstimatePayload,
  DirectorWorkspaceSnapshot,
  LatestDeliveryRead,
  ProductionQualityReportPayload,
  RepairOptionContract,
  TrialReviewPayload,
} from "./types";

type ProductionStageProps = {
  projectId: string;
  snapshot: DirectorWorkspaceSnapshot;
  refresh: () => Promise<unknown>;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
};

type RepairPlanPayload = {
  batch_id: string;
  quality_report_version_id: string;
  options: RepairOptionContract[];
  additional_budget_required: true;
};

type DownloadRole = "mp4" | "srt" | "timeline_json" | "package_zip";

const DOWNLOADS: Array<{ role: DownloadRole; label: string }> = [
  { role: "mp4", label: "成片 MP4" },
  { role: "srt", label: "字幕 SRT" },
  { role: "timeline_json", label: "时间线 JSON" },
  { role: "package_zip", label: "完整素材包 ZIP" },
];

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatMoney(value: string | null, currency: string): string {
  return value === null ? "价格尚未验证" : `${value} ${currency}`;
}

function productionBatch(snapshot: DirectorWorkspaceSnapshot) {
  return [...snapshot.production_batches]
    .reverse()
    .find((batch) => batch.batch_kind === "production") ?? null;
}

function activeExecutionBatch(snapshot: DirectorWorkspaceSnapshot) {
  const repair = [...snapshot.production_batches]
    .reverse()
    .find((batch) => batch.batch_kind === "repair");
  if (repair && ["production_running", "final_review"].includes(snapshot.workflow.status)) return repair;
  return productionBatch(snapshot);
}

function isProductionReport(value: unknown): value is ProductionQualityReportPayload {
  return Boolean(value && typeof value === "object" && Array.isArray((value as ProductionQualityReportPayload).shot_reports));
}

function ProductionBudgetAuthorization(props: ProductionStageProps & { cost: CostEstimatePayload }) {
  const { projectId, snapshot, cost, refresh, onMessage, onError } = props;
  const [limit, setLimit] = useState(cost.production_total ?? "");
  const [acknowledged, setAcknowledged] = useState(false);
  const estimate = Number(cost.production_total ?? 0);
  const parsedLimit = Number(limit);
  const pricingReady = isProductionPricingReady(cost);
  const limitReady = Number.isFinite(parsedLimit) && parsedLimit > 0 && parsedLimit >= estimate;
  const mutation = useMutation({
    mutationFn: async () => {
      const reusable = snapshot.budget_authorizations.find(
        (item) =>
          item.authorization_kind === "production_budget" &&
          item.status === "active" &&
          item.pricing_snapshot_id === cost.pricing_snapshot_id &&
          item.currency === cost.currency &&
          Number(item.limit_amount) === parsedLimit,
      );
      const authorization = reusable ?? await authorizeDirectorBudget(projectId, {
        authorization_kind: "production_budget",
        idempotency_key: commandKey("production-budget"),
        pricing_snapshot_id: cost.pricing_snapshot_id,
        limit_amount: limit,
        currency: cost.currency,
        expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      });
      await approveDirectorStage(projectId, "production_budget", commandKey("approve-production-budget"), authorization.id);
    },
    onSuccess: async () => {
      onMessage("正式生产预算已授权。系统尚未生成媒体，需再点击“开始正式生产”。");
      await refresh();
    },
    onError: async (error) => { onError(errorText(error)); await refresh(); },
  });
  return (
    <section className="panel director-budget-panel" data-testid="production-budget-panel">
      <div className="panel-header"><div><h3>硬确认 4 / 4 · 正式生产预算</h3><p className="muted">接受试拍不等于授权全片；这是独立的费用边界。</p></div><strong>{formatMoney(cost.production_total, cost.currency)}</strong></div>
      <ul className="dense">{cost.production.map((line) => <li key={line.purpose}><span>{line.purpose} × {line.quantity}</span><strong>{formatMoney(line.estimated_amount, line.currency)}</strong></li>)}</ul>
      {!pricingReady && <div className="callout warn">供应商价格尚未形成可验证快照。未知费用不会被授权。</div>}
      <label>正式生产最高预算（{cost.currency}）<input type="number" min="0" step="0.01" value={limit} onChange={(event) => setLimit(event.target.value)} /></label>
      <label className="director-rights-confirm"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我接受试拍证据和已知风险，同意在不超过此上限的范围内生产完整短剧</span></label>
      <button type="button" className="accent" disabled={!pricingReady || !limitReady || !acknowledged || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "正在记录授权…" : "确认并授权正式生产预算"}</button>
    </section>
  );
}

function ProductionProgress(props: ProductionStageProps) {
  const { projectId, snapshot, refresh, onMessage, onError } = props;
  const queryClient = useQueryClient();
  const batch = activeExecutionBatch(snapshot);
  const project = useQuery({ queryKey: ["snapshot", projectId], queryFn: () => fetchSnapshot(projectId), refetchInterval: 2_500 });
  const runs = useMemo(
    () => (project.data?.node_runs ?? []).filter((run) => String(run.input_snapshot.production_batch_id ?? "") === batch?.id),
    [batch?.id, project.data?.node_runs],
  );
  const allTerminal = Boolean(batch && areTrialRunsTerminal(runs.map((run) => run.status)));
  const hasRecoverableRepair = Boolean(
    batch?.batch_kind === "repair" && runs.some((run) =>
      run.status === "failed" || (
        run.node_key === "video" &&
        run.status === "queued" &&
        !run.input_snapshot.dispatch_generation
      ),
    ),
  );
  const materialize = useMutation({
    mutationFn: () => materializeProduction(projectId, commandKey("materialize-production")),
    onSuccess: async (result) => {
      onMessage(`正式生产已开始，共创建 ${result.node_runs.length} 个受控节点。`);
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: ["snapshot", projectId] })]);
    },
    onError: async (error) => { onError(errorText(error)); await refresh(); },
  });
  const inspect = useMutation({
    mutationFn: () => {
      if (!batch) throw new Error("正式生产批次尚未创建");
      return inspectProduction(projectId, batch.id, commandKey("inspect-production"));
    },
    onSuccess: async () => { onMessage("正式生产质检完成，请逐镜验收。 "); await refresh(); },
    onError: (error) => onError(errorText(error)),
  });
  const resumeRepair = useMutation({
    mutationFn: () => {
      if (!batch || batch.batch_kind !== "repair") throw new Error("缺少可恢复的局部修复批次");
      return resumePreSubmitRepair(projectId, batch.id, commandKey("resume-pre-submit-repair"));
    },
    onSuccess: async () => {
      onMessage("已继续原局部修复；预算和 Provider 调用上限没有增加。");
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: ["snapshot", projectId] })]);
    },
    onError: async (error) => { onError(errorText(error)); await refresh(); },
  });
  return (
    <section className="panel" data-testid="production-progress">
      <div className="panel-header"><div><h3>正式生产进度</h3><p className="muted">节点来自批次真实快照；页面不会用估算动画代替执行状态。</p></div><strong>{batch?.status ?? "尚未开始"}</strong></div>
      {!batch && <button type="button" className="accent" disabled={materialize.isPending} onClick={() => materialize.mutate()}>{materialize.isPending ? "正在创建受控任务…" : "开始正式生产"}</button>}
      {batch && <>
        <div className="status-grid"><div className="status-card"><span className="status-label">镜头</span><strong>{batch.selected_shot_ids.length}</strong></div><div className="status-card"><span className="status-label">节点</span><strong>{runs.length}</strong></div><div className="status-card"><span className="status-label">终态节点</span><strong>{runs.filter((run) => !["queued", "running", "leased"].includes(run.status)).length}</strong></div></div>
        <div className="director-trial-run-list">{runs.map((run) => <article key={run.id}><div><strong>{run.node_key}</strong><span>{run.status}</span></div>{run.error_code && <p className="status-bad">{run.error_code}：{run.error_summary}</p>}</article>)}</div>
        {hasRecoverableRepair && <button type="button" className="accent" disabled={resumeRepair.isPending} onClick={() => resumeRepair.mutate()}>{resumeRepair.isPending ? "正在恢复原修复…" : "继续本次局部修复（不新增预算）"}</button>}
        {snapshot.workflow.status === "production_running" && <button type="button" className="primary" disabled={!allTerminal || inspect.isPending} onClick={() => inspect.mutate()}>{inspect.isPending ? "正在汇总逐镜证据…" : allTerminal ? "运行已结束，生成逐镜质量报告" : "等待所有节点结束"}</button>}
      </>}
    </section>
  );
}

function ProductionReview(props: ProductionStageProps & { report: ProductionQualityReportPayload }) {
  const { projectId, snapshot, report, refresh, onMessage, onError } = props;
  const batch = snapshot.production_batches.find((item) => item.id === report.batch_id)
    ?? activeExecutionBatch(snapshot);
  const project = useQuery({ queryKey: ["snapshot", projectId], queryFn: () => fetchSnapshot(projectId) });
  const batchRuns = useMemo(
    () => (project.data?.node_runs ?? []).filter((run) => String(run.input_snapshot.production_batch_id ?? "") === batch?.id),
    [batch?.id, project.data?.node_runs],
  );
  const [decisions, setDecisions] = useState<Record<string, "accept" | "repair" | "stop">>({});
  const [note, setNote] = useState("");
  const mutation = useMutation({
    mutationFn: async () => {
      if (!batch) throw new Error("正式生产批次不存在");
      const result = await reviewProduction(projectId, { batch_id: batch.id, decisions, user_note: note, idempotency_key: commandKey("review-production") });
      const allAccepted = Object.values(decisions).every((decision) => decision === "accept");
      const delivery = allAccepted && batch.batch_kind === "production" ? await exportProduction(projectId, batch.id) : null;
      return { result, delivery };
    },
    onSuccess: async ({ delivery }) => {
      onMessage(delivery ? "所有镜头已验收并按精确血缘导出。" : "逐镜决定已记录；修复不会在额外预算确认前启动。 ");
      await refresh();
    },
    onError: async (error) => { onError(errorText(error)); await refresh(); },
  });
  const complete = report.shot_reports.length > 0 && report.shot_reports.every((shot) => decisions[shot.logical_shot_id]);
  const subjectiveAccepts = report.shot_reports.some(
    (shot) => decisions[shot.logical_shot_id] === "accept" && ["warning", "needs_human"].includes(shot.overall_status),
  );
  const reviewReady = complete && (!subjectiveAccepts || Boolean(note.trim()));
  return (
    <section className="panel" data-testid="production-review">
      <div className="panel-header"><div><h3>逐镜质量验收</h3><p className="muted">每个镜头必须明确接受、修复或停止；硬阻断不能被接受。</p></div><strong>{report.overall_status}</strong></div>
      {batch?.batch_kind === "repair" && project.data && (
        <TrialMediaEvidence projectId={projectId} project={project.data} trialRuns={batchRuns} snapshot={snapshot} evidenceKind="repair" />
      )}
      <div className="director-shot-review-list">{report.shot_reports.map((shot) => {
        const blocked = shot.hard_blockers.length > 0 || shot.overall_status === "blocked";
        return <article key={shot.logical_shot_id}><header><strong>{shot.logical_shot_id}</strong><span>{shot.overall_status}</span></header><p>{shot.dimensions.filter((item) => item.status !== "passed").map((item) => item.summary).join("；") || "自动证据未发现异常。"}</p><div className="director-shot-decisions"><button type="button" className={decisions[shot.logical_shot_id] === "accept" ? "selected" : ""} disabled={blocked} onClick={() => setDecisions((value) => ({ ...value, [shot.logical_shot_id]: "accept" }))}>接受</button><button type="button" className={decisions[shot.logical_shot_id] === "repair" ? "selected" : ""} onClick={() => setDecisions((value) => ({ ...value, [shot.logical_shot_id]: "repair" }))}>局部修复</button><button type="button" className={decisions[shot.logical_shot_id] === "stop" ? "selected" : ""} onClick={() => setDecisions((value) => ({ ...value, [shot.logical_shot_id]: "stop" }))}>停止</button></div>{blocked && <small className="status-bad">硬阻断：{shot.hard_blockers.join("；")}</small>}</article>;
      })}</div>
      <label>给 AI 导演的验收说明<textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} /></label>
      <button type="button" className="accent" disabled={!reviewReady || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "正在提交并处理…" : complete && Object.values(decisions).every((value) => value === "accept") ? "全部接受并精确导出" : "提交逐镜决定"}</button>
      {subjectiveAccepts && !note.trim() && <p className="status-pending">接受需要人工判断的镜头前，请填写验收理由；原质量报告不会被改写。</p>}
    </section>
  );
}

function RepairPlanning(props: ProductionStageProps & { plan: RepairPlanPayload | null }) {
  const { projectId, snapshot, plan, refresh, onMessage, onError } = props;
  const quality = snapshot.current_artifacts.quality_report;
  const qualityPayload = quality?.payload;
  const qualityBatchId = qualityPayload && typeof qualityPayload === "object" && "batch_id" in qualityPayload
    ? String(qualityPayload.batch_id)
    : null;
  const batch = qualityBatchId
    ? snapshot.production_batches.find((item) => item.id === qualityBatchId) ?? null
    : productionBatch(snapshot) ?? [...snapshot.production_batches].reverse().find((item) => item.batch_kind === "trial") ?? null;
  const [selectedId, setSelectedId] = useState("");
  const selected = plan?.options.find((option) => option.repair_option_id === selectedId) ?? null;
  const [limit, setLimit] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const mutation = useMutation({
    mutationFn: () => {
      if (!batch || !quality) throw new Error("缺少修复所需的批次或质量报告");
      return planRepairs(projectId, { batch_id: batch.id, quality_report_version_id: quality.id, idempotency_key: commandKey("plan-repairs") });
    },
    onSuccess: async () => { onMessage("已生成三个结构化局部修复方案；尚未产生新媒体费用。 "); await refresh(); },
    onError: (error) => onError(errorText(error)),
  });
  const execute = useMutation({
    mutationFn: async () => {
      if (!selected || selected.estimated_cost === null) throw new Error("修复价格尚未验证");
      const authorization = await authorizeDirectorBudget(projectId, {
        authorization_kind: "repair_budget",
        idempotency_key: commandKey("repair-budget"),
        pricing_snapshot_id: `repair-plan:${snapshot.current_artifacts.repair_plan?.id ?? "unknown"}`,
        limit_amount: limit,
        currency: selected.currency,
        expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      });
      return authorizeAndMaterializeRepair(projectId, {
        repair_option_id: selected.repair_option_id,
        budget_authorization_id: authorization.id,
        idempotency_key: commandKey("materialize-repair"),
      });
    },
    onSuccess: async (result) => {
      onMessage(`局部修复已开始，共创建 ${result.node_runs.length} 个受控节点。`);
      await refresh();
    },
    onError: (error) => onError(errorText(error)),
  });
  if (!plan || snapshot.workflow.status === "repair_proposed") return <section className="panel"><h3>{plan ? "更新局部修复方案" : "生成局部修复方案"}</h3><p>AI 导演将基于最新质量证据定位失败原因、可复用资产和预计改动。本动作不生成媒体，也不会沿用上一次失败后的旧授权。</p><button type="button" className="accent" disabled={!batch || !quality || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "正在诊断…" : plan ? "基于最新证据重新生成方案" : "生成三个修复方案"}</button></section>;
  const estimated = Number(selected?.estimated_cost ?? 0);
  const parsedLimit = Number(limit);
  const ready = Boolean(selected && selected.estimated_cost !== null && Number.isFinite(parsedLimit) && parsedLimit > 0 && parsedLimit >= estimated);
  return <section className="panel"><div className="panel-header"><div><h3>局部修复方案</h3><p className="muted">选择方案不会生成媒体；额外费用在下一步单独授权。</p></div><strong>{plan.options.length} 个</strong></div><div className="director-repair-options">{plan.options.map((option) => <article key={option.repair_option_id} className={selectedId === option.repair_option_id ? "selected" : ""}><header><strong>{option.title}</strong><span>{formatMoney(option.estimated_cost, option.currency)}</span></header><p>{option.diagnosis}</p><small>影响镜头：{option.affected_shot_ids.join("、")}</small><ul>{option.changes.map((change) => <li key={`${change.target}:${change.summary}`}>{change.target}：{change.summary}</li>)}</ul>{option.residual_risks.length > 0 && <p className="muted">剩余风险：{option.residual_risks.join("；")}</p>}<button type="button" onClick={() => { setSelectedId(option.repair_option_id); setLimit(option.estimated_cost ?? ""); setAcknowledged(false); }}>选择这个方案</button></article>)}</div>{selected && <section className="director-repair-authorization" data-testid="repair-budget-panel"><h4>额外修复预算授权</h4><p>方案：{selected.title} · 估算 {formatMoney(selected.estimated_cost, selected.currency)}</p>{selected.estimated_cost === null && <div className="callout warn">该方案价格未知，不能授权或生成媒体。</div>}<label>本次修复最高预算（{selected.currency}）<input type="number" min="0" step="0.01" value={limit} onChange={(event) => setLimit(event.target.value)} /></label><label className="director-rights-confirm"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我已看过改动范围、可复用资产、剩余风险和额外费用，同意局部重生成</span></label><button type="button" className="accent" disabled={!ready || !acknowledged || execute.isPending} onClick={() => execute.mutate()}>{execute.isPending ? "正在授权并创建局部任务…" : "授权额外预算并开始局部修复"}</button></section>}</section>;
}

function Delivery({ projectId, delivery, onError }: { projectId: string; delivery: LatestDeliveryRead; onError: (message: string) => void }) {
  const [urls, setUrls] = useState<Partial<Record<DownloadRole, string>>>({});
  const mutation = useMutation({
    mutationFn: async () => {
      const available = DOWNLOADS.filter(
        (item) => item.role !== "mp4" || delivery.items.some((entry) => entry.kind === "program_mp4"),
      );
      const grants = await Promise.all(available.map(async (item) => ({ item, grant: await grantExportDownload(projectId, delivery.export_id, item.role) })));
      return Object.fromEntries(grants.map(({ item, grant }) => [item.role, exportDownloadUrl(projectId, grant.export_id, grant.token, item.role)])) as Record<DownloadRole, string>;
    },
    onSuccess: setUrls,
    onError: (error) => onError(errorText(error)),
  });
  return <section className="panel" data-testid="director-delivery"><div className="panel-header"><div><h3>完整交付</h3><p className="muted">精确使用已验收镜头血缘，已恢复 {delivery.items.length} 项制品记录。</p></div><span className="status-ok">{delivery.status}</span></div>{delivery.program_mp4_error && <div className="callout warn">MP4 导出异常：{delivery.program_mp4_error}</div>}<div className="director-download-grid">{DOWNLOADS.map((item) => urls[item.role] ? <a key={item.role} href={urls[item.role]} target="_blank" rel="noreferrer">下载{item.label}</a> : <span key={item.role}>{item.label} · {item.role === "mp4" && !delivery.items.some((entry) => entry.kind === "program_mp4") ? "导出不可用" : "待授权下载"}</span>)}</div><button type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending}>{mutation.isPending ? "正在申请下载授权…" : "准备四项下载"}</button></section>;
}

export function ProductionStage(props: ProductionStageProps) {
  const { snapshot } = props;
  const cost = artifactPayload<CostEstimatePayload>(snapshot, "cost_estimate");
  const trialReview = artifactPayload<TrialReviewPayload>(snapshot, "trial_review");
  const qualityRaw = snapshot.current_artifacts.quality_report?.payload;
  const productionQuality = isProductionReport(qualityRaw) ? qualityRaw : null;
  const repairPlan = artifactPayload<RepairPlanPayload>(snapshot, "repair_plan");
  const status = snapshot.workflow.status;
  return <section data-testid="production-stage">
    <section className="panel director-stage-intro"><div><span className="director-stage-kicker">阶段 4</span><h2>正式生产与交付</h2></div><p>用试拍证据决定是否投入全片；正式生产、局部修复和新增媒体费用分别授权。</p></section>
    {trialReview && <section className="panel director-locked-summary"><div className="panel-header"><h3>试拍决定</h3><strong>{trialReview.decision === "accept" ? "已接受" : trialReview.decision === "repair" ? "先修复" : "已停止"}</strong></div>{trialReview.user_note && <p>{trialReview.user_note}</p>}</section>}
    {status === "awaiting_production_authorization" && cost && <ProductionBudgetAuthorization {...props} cost={cost} />}
    {status === "awaiting_production_authorization" && !cost && <div className="callout warn">缺少正式生产成本快照，不能授权。</div>}
    {status === "production_running" && <ProductionProgress {...props} />}
    {status === "final_review" && productionQuality && <ProductionReview {...props} report={productionQuality} />}
    {status === "final_review" && !productionQuality && <div className="callout warn">快照缺少正式生产逐镜质量报告，不能验收。</div>}
    {status === "repair_proposed" && <RepairPlanning {...props} plan={repairPlan} />}
    {status === "awaiting_repair_authorization" && <RepairPlanning {...props} plan={repairPlan} />}
    {status === "cancelled" && <section className="panel"><h3>创作已停止</h3><p>系统已记录停止决定，没有新的媒体请求或费用。</p></section>}
    {status === "assembling" && <section className="panel"><h3>所有镜头已接受</h3><p>精确导出尚未完成，可安全重试；不会重新生成媒体。</p><RetryExport {...props} /></section>}
    {status === "completed" && snapshot.latest_delivery && <Delivery projectId={props.projectId} delivery={snapshot.latest_delivery} onError={props.onError} />}
    {status === "completed" && !snapshot.latest_delivery && <div className="callout warn">工作流已完成，但聚合快照尚未返回 latest_delivery，刷新后无法安全恢复四项下载信息。</div>}
  </section>;
}

function RetryExport(props: ProductionStageProps) {
  const batch = productionBatch(props.snapshot);
  const mutation = useMutation({ mutationFn: () => { if (!batch) throw new Error("缺少正式生产批次"); return exportProduction(props.projectId, batch.id); }, onSuccess: async () => { props.onMessage("精确导出完成。"); await props.refresh(); }, onError: (error) => props.onError(errorText(error)) });
  return <button type="button" className="accent" disabled={!batch || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "正在精确导出…" : "重试精确导出"}</button>;
}
