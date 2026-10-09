import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Button, Checkbox, Input, Textarea } from "../../components/ui";
import { ApiError, getSelectedWorkspaceId, listModels } from "../../lib/api";
import {
  capabilityGapReason,
  capabilityGapSeverityLabel,
  executionModelLabel,
  referenceDeliveryLabel,
} from "../../lib/executionPlanLabels";
import { queryKeys } from "../../lib/queryKeys";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { REFERENCE_PURPOSES } from "../model-controls";
import { reviewTargetHref } from "./reviewTarget";
import {
  REPAIR_OPTION_LABEL,
  REPAIR_OPTION_STAGES,
  closeRepair,
  createRepair,
  executeRepairStep,
  fetchRepairPlan,
  listRepairs,
  previewRepairStep,
  readRepair,
  readRepairSubmission,
  repairCanPreviewStep,
  repairHasUnknownSubmission,
  repairStageLabel,
  repairStepActionLabel,
  repairSubmissionScope,
  saveRepairSubmission,
  type RepairOption,
  type RepairRequestRead,
  type RepairStepPlanBody,
  type RepairStepPlanRead,
  type RepairSubmission,
} from "./repairApi";

type RepairPlanPanelProps = {
  projectId: string;
  shotId: string;
  /** Dismiss the panel, not the persisted repair or its running task. */
  onClose?: () => void;
};

type RepairContext = Pick<RepairPlanPanelProps, "projectId" | "shotId">;

function errorCode(error: unknown): string {
  return error instanceof ApiError ? String(error.details.code ?? error.code) : "";
}

function StepHistory({
  projectId,
  shotId,
  request,
}: RepairContext & { request: RepairRequestRead }) {
  return (
    <ol data-testid="repair-steps">
      {request.steps.map((step) => (
        <li key={step.id} data-testid={`repair-step-${step.ordinal}`}>
          第 {step.ordinal} 步 · {repairStageLabel(step.stage)}
          {step.node_run_status && ` · 运行状态 ${nodeRunStatusLabel(step.node_run_status)}`}
          {` · ${repairStepActionLabel(
            step.node_run_error_code === "PROVIDER_SUBMISSION_UNKNOWN"
              ? "reconcile_submission"
              : step.next_action,
          )}`}
          {step.result_artifact_id &&
            ["completed", "cached", "completed_after_cancel"].includes(
              step.node_run_status ?? "",
            ) &&
            (step.stage === "keyframe_regenerate" || step.stage === "video_rerun") && (
              <a
                href={reviewTargetHref(projectId, {
                  shotId,
                  artifactId: step.result_artifact_id,
                  stage: step.stage === "keyframe_regenerate" ? "formal_keyframe" : "formal_video",
                  reviewKind: step.stage === "keyframe_regenerate" ? "identity" : "video_drift",
                  repairRequestId: request.id,
                  repairStepId: step.id,
                })}
              >
                审查本步候选
              </a>
            )}
        </li>
      ))}
    </ol>
  );
}

function referencePurposeLabel(purpose: string): string {
  return REFERENCE_PURPOSES.find((entry) => entry.value === purpose)?.label ?? "参考素材";
}

function ExecutionPreview({ preview }: { preview: RepairStepPlanRead }) {
  const models = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
    retry: false,
  });
  const model = executionModelLabel(
    preview.plan.resolved_model?.resolved_model_id,
    Array.isArray(models.data) ? models.data : undefined,
  );
  return (
    <section aria-label="本步执行计划" data-testid="repair-step-preview">
      <h4>
        第 {preview.step_ordinal} 步 · {repairStageLabel(preview.stage)}
      </h4>
      <p data-testid="repair-step-scope">
        执行范围：仅当前镜头的{preview.stage === "keyframe_regenerate" ? "关键帧" : "视频"}候选。
        不是标注区域的局部修补，不自动替换正式版本。
      </p>
      <p data-testid="repair-step-model">实际模型：{model.label}</p>
      <details>
        <summary>模型身份与计划凭据（只读）</summary>
        <p>模型：{model.raw || "尚未解析"}</p>
        <p>模型绑定：{preview.plan.resolved_model?.provider_model_binding_id ?? "无"}</p>
        <p>计划指纹：{preview.plan.plan_fingerprint ?? "无"}</p>
      </details>
      <h4>本步实际引用</h4>
      <ul data-testid="repair-step-references">
        {(preview.plan.planned_references ?? []).map((reference, index) => (
          <li
            key={`${reference.artifact_id ?? reference.asset_version_id ?? "reference"}-${index}`}
          >
            <span data-testid={`repair-reference-label-${index + 1}`}>
              {referencePurposeLabel(reference.purpose)} {index + 1} ·{" "}
              {referenceDeliveryLabel(reference.delivery)}
            </span>
            <details data-testid={`repair-reference-identity-${index + 1}`}>
              <summary>查看引用 {index + 1} 身份（只读）</summary>
              <p>产物：{reference.artifact_id ?? "无"}</p>
              <p>素材版本：{reference.asset_version_id ?? "无"}</p>
              <p>用途凭据：{reference.purpose}</p>
            </details>
          </li>
        ))}
      </ul>
      {!preview.plan.planned_references?.length && <p className="muted">本步没有素材引用。</p>}
      {Boolean(preview.plan.capability_gaps?.length) && (
        <section aria-label="模型能力差异" data-testid="repair-capability-gaps">
          <h4>模型能力差异</h4>
          <ul>
            {preview.plan.capability_gaps?.map((gap, index) => (
              <li key={index} className={gap.severity === "fatal" ? "flash err" : "flash"}>
                {capabilityGapSeverityLabel(gap.severity)}：
                {gap.severity === "warning"
                  ? "部分引用或控制只能近似表达，不等于完全支持。"
                  : capabilityGapReason(gap.reason).label}
                {Boolean(gap.controls?.length) && (
                  <p>涉及用途：{gap.controls?.map(referencePurposeLabel).join("、")}</p>
                )}
                <details>
                  <summary>能力差异依据（只读）</summary>
                  <p>{gap.reason}</p>
                  <p>{gap.controls?.join("、")}</p>
                </details>
              </li>
            ))}
          </ul>
        </section>
      )}
      {Boolean(preview.plan.accepted_approximations?.length) && (
        <section aria-label="冻结计划已接受的近似" data-testid="repair-accepted-approximations">
          <h4>冻结计划已接受的近似</h4>
          <ul>
            {preview.plan.accepted_approximations?.map((purpose, index) => (
              <li key={`${purpose}-${index}`}>
                {referencePurposeLabel(purpose)} · 近似处理
                <details>
                  <summary>接受凭据（只读）</summary>
                  <p>{purpose}</p>
                </details>
              </li>
            ))}
          </ul>
        </section>
      )}
      <label>
        本步实际提示词
        <Textarea readOnly rows={6} value={preview.plan.prompt} data-testid="repair-step-prompt" />
      </label>
      <p className="muted">
        执行将调用以上模型，可能产生费用；这里不提供确定报价。只执行这一媒体步骤，之后仍须人工审查并明确采用。
      </p>
    </section>
  );
}

/** One mounted repair owns its preview and a durable, immutable submission identity. */
function ActiveRepair({
  projectId,
  shotId,
  request,
  readable,
  onRead,
  onRefresh,
}: RepairContext & {
  request: RepairRequestRead;
  readable: boolean;
  onRead: (request: RepairRequestRead) => void;
  onRefresh: () => void;
}) {
  const scope = repairSubmissionScope(getSelectedWorkspaceId(), projectId, shotId, request.id);
  const [recovery, setRecovery] = useState<{ record: RepairSubmission | null; blocked: boolean }>(
    () => {
      try {
        return { record: readRepairSubmission(scope), blocked: false };
      } catch {
        return { record: null, blocked: true };
      }
    },
  );
  const [feedback, setFeedback] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [acceptApproximations, setAcceptApproximations] = useState(false);
  const dispatching = useRef(false);
  const record = recovery.record;
  const observedStep = record
    ? request.steps.find((step) => step.ordinal === record.input.expected_step_ordinal)
    : undefined;
  // An observed media step is authoritative even if this browser lost its POST response.
  const pending = observedStep ? null : record;
  const unknown = repairHasUnknownSubmission(request) || pending?.outcome === "unknown_submission";
  const executable = readable && repairCanPreviewStep(request) && !unknown && !recovery.blocked;

  function remember(value: RepairSubmission | null) {
    // Persist BEFORE sending. If storage is denied, no potentially billable request is sent.
    try {
      saveRepairSubmission(scope, value);
      setRecovery({ record: value, blocked: false });
    } catch (error) {
      setRecovery((current) => ({ ...current, blocked: true }));
      throw error;
    }
  }

  useEffect(() => {
    if (!observedStep) return;
    try {
      saveRepairSubmission(scope, null);
      setRecovery({ record: null, blocked: false });
    } catch {
      // Existing server receipts still prevent re-execution even if local cleanup fails.
    }
  }, [observedStep, scope]);

  const preview = useMutation({
    mutationFn: (input: RepairStepPlanBody | undefined) =>
      previewRepairStep(projectId, shotId, request.id, input),
    retry: false,
    onMutate: () => {
      setAcknowledged(false);
      setFeedback(null);
    },
    onError: () => {
      setFeedback(
        "无法预览本步。请刷新修复状态，核对人工审核、正式素材及模型配置后再预览；未提交生成。",
      );
      onRefresh();
    },
  });
  const resetPreview = preview.reset;
  useEffect(() => {
    resetPreview();
    setAcknowledged(false);
    setAcceptApproximations(false);
  }, [request.next_step_ordinal, resetPreview]);
  const displayed = preview.data;
  const matches = Boolean(
    displayed &&
    displayed.repair_id === request.id &&
    displayed.step_ordinal === request.next_step_ordinal &&
    displayed.stage === REPAIR_OPTION_STAGES[request.option][displayed.step_ordinal - 1] &&
    displayed.plan.project_id === projectId &&
    displayed.plan.shot_id === shotId &&
    displayed.plan.stage ===
      (displayed.stage === "keyframe_regenerate" ? "image_keyframe" : "video"),
  );
  const supported = Boolean(
    displayed?.plan.resolved_model?.status === "RESOLVED" &&
    Boolean(displayed.plan.resolved_model.resolved_model_id) &&
    typeof displayed.plan.prompt === "string" &&
    Boolean(displayed.plan.prompt.trim()) &&
    /^[a-f0-9]{64}$/i.test(displayed.plan.plan_fingerprint ?? "") &&
    !(displayed.plan.capability_gaps ?? []).some((gap) =>
      ["fatal", "blocker"].includes(gap.severity),
    ) &&
    !(displayed.plan.planned_references ?? []).some(
      (reference) => reference.delivery === "unsupported",
    ) &&
    !displayed.plan.unsupported_controls?.length,
  );

  const approximateReferences = (displayed?.plan.planned_references ?? []).filter(
    (reference) => reference.delivery === "approximate",
  );
  const acceptedApproximations = displayed?.plan.accepted_approximations ?? [];
  const needsApproximationConsent = Boolean(
    approximateReferences.length ||
    displayed?.plan.approximate_controls?.length ||
    displayed?.plan.capability_gaps?.some((gap) => gap.severity === "warning") ||
    acceptedApproximations.length,
  );
  // A checkbox is not a frozen plan. Its new value must return from step-plan first.
  const approximationConfirmed =
    Boolean(preview.variables?.accept_approximations) === acceptApproximations &&
    (!needsApproximationConsent ||
      (acceptApproximations &&
        acceptedApproximations.length > 0 &&
        approximateReferences.every((reference) =>
          acceptedApproximations.includes(reference.purpose),
        )));

  const runStep = useMutation({
    mutationFn: async ({
      submission,
      recovering,
    }: {
      submission: RepairSubmission;
      recovering: boolean;
    }) => {
      if (recovering) {
        // Never blind-retry: read facts first, and never replace the original payload/key.
        const current = await readRepair(projectId, shotId, request.id);
        onRead(current);
        if (
          !repairCanPreviewStep(current) ||
          current.next_step_ordinal !== submission.input.expected_step_ordinal
        )
          return null;
      }
      remember(submission);
      return executeRepairStep(projectId, shotId, request.id, submission.input);
    },
    retry: false,
    onSuccess: (result, { submission }) => {
      if (!result) {
        setFeedback("已同步原修复状态，没有再次提交生成。请按当前状态继续。");
        return;
      }
      const outcome = "accepted" as const;
      try {
        remember({ ...submission, outcome });
      } catch {
        // The original key was already saved before POST; don't lose the in-memory receipt.
        setRecovery({ record: { ...submission, outcome }, blocked: true });
      }
      setAcknowledged(false);
      setFeedback("已提交本步，正在同步原运行；不会自动执行下一步。");
      onRefresh();
    },
    onError: (error, { submission }) => {
      const code = errorCode(error);
      if (["REPAIR_STEP_PLAN_MISMATCH", "REPAIR_STEP_STALE"].includes(code)) {
        try {
          remember(null);
        } catch {
          setRecovery((value) => ({ ...value, blocked: true }));
        }
        preview.reset();
        setAcknowledged(false);
        setAcceptApproximations(false);
        setFeedback(
          "本步计划已过期，未提交新计划。请重新预览实际模型、引用、提示词及范围，再显式确认执行。",
        );
      } else if (["PROVIDER_SUBMISSION_UNKNOWN", "REPAIR_SUBMISSION_UNKNOWN"].includes(code)) {
        try {
          remember({ ...submission, outcome: "unknown_submission" });
        } catch {
          setRecovery({ record: { ...submission, outcome: "unknown_submission" }, blocked: true });
        }
        setFeedback("原提交结果未知，可能已计费。禁止重试，请核对原运行。");
      } else {
        setFeedback(
          "未取得明确的提交回执。请先刷新原运行状态；若仍无记录，只能使用下方原计划、原步骤及同一请求键恢复提交。",
        );
      }
      onRefresh();
    },
  });

  function submit(submission: RepairSubmission, recovering: boolean) {
    if (dispatching.current) return;
    dispatching.current = true;
    runStep.mutate(
      { submission, recovering },
      {
        onSettled: () => {
          dispatching.current = false;
        },
      },
    );
  }

  const close = useMutation({
    mutationFn: (reason: "completed" | "abandoned") =>
      closeRepair(projectId, shotId, request.id, { reason }),
    retry: false,
    onSuccess: (closed) => {
      onRead(closed);
      onRefresh();
    },
    onError: () => {
      setFeedback(
        "未能结束修复。运行中或提交结果未知时不能关闭；请刷新状态，需停止时前往原运行的取消入口。",
      );
      onRefresh();
    },
  });
  const busy = runStep.isPending || close.isPending || preview.isPending;
  const closable =
    readable &&
    !busy &&
    !pending &&
    !unknown &&
    !recovery.blocked &&
    request.next_action !== "wait";

  return (
    <div data-testid="repair-active" data-next-action={request.next_action}>
      <p>
        进行中的修复：{REPAIR_OPTION_LABEL[request.option]} ·{" "}
        {repairStepActionLabel(unknown ? "reconcile_submission" : request.next_action)}
      </p>
      <StepHistory projectId={projectId} shotId={shotId} request={request} />
      <Button tone="ghost" disabled={busy} onClick={onRefresh} data-testid="repair-refresh">
        刷新修复状态
      </Button>
      {request.next_action === "wait" && !unknown && (
        <p className="flash" data-testid="repair-wait-hint" role="status">
          本步仍在运行，正在自动同步；现在无需人工审查，也不能执行下一步或结束修复。
        </p>
      )}
      {unknown && (
        <p className="flash err" data-testid="repair-unknown-hint" role="alert">
          原提交结果未知，可能已计费。请核对原运行，不要重试、关闭后重做或创建新请求。
        </p>
      )}
      {(request.next_action === "wait" || unknown || pending) && (
        <p>
          <a href={`/projects/${encodeURIComponent(projectId)}/production`}>
            前往制作总览，在“生成任务”查看原运行及取消入口
          </a>
        </p>
      )}
      {request.next_action === "human_decision" && !unknown && (
        <p className="flash" data-testid="repair-review-hint" role="status">
          请通过“审查本步候选”检查对应结果，通过人工审核后明确设为正式，才可继续。修复尚未完成。
        </p>
      )}
      {request.next_action === "close_or_replan" && !unknown && (
        <p className="flash" role="status">
          本次结果无法继续。可显式放弃本次修复，再预览并确认新计划；不会自动重试。
        </p>
      )}
      {request.next_action === "ready_to_close" && !unknown && (
        <p className="flash" data-testid="repair-ready-to-close" role="status">
          最后一步视频已通过审查并设为正式。请显式完成本次修复；不会自动关闭标注。
        </p>
      )}
      {recovery.blocked && (
        <p className="flash err" role="alert">
          无法安全保存或恢复提交凭据。已阻止新的生成，请先核对原运行及浏览器存储权限。
        </p>
      )}
      {pending && !unknown && (
        <section data-testid="repair-recovery">
          <p role="status">
            正在恢复第 {pending.input.expected_step_ordinal}{" "}
            步的原提交；不预览或自动提交另一份计划。
          </p>
          <details>
            <summary>原提交凭据（只读）</summary>
            <p>{pending.input.idempotency_key}</p>
            <p>{pending.input.expected_plan_fingerprint}</p>
            <p>原近似选择：{pending.input.accept_approximations ? "已接受" : "未接受"}</p>
          </details>
          {pending.outcome === "unconfirmed" && (
            <Button
              disabled={!executable || busy}
              onClick={() => submit(pending, true)}
              data-testid="repair-retry-submission"
            >
              核对后按原请求恢复提交
            </Button>
          )}
        </section>
      )}
      {executable && !pending && (
        <>
          <Button
            disabled={busy}
            onClick={() =>
              preview.mutate(acceptApproximations ? { accept_approximations: true } : undefined)
            }
            data-testid="repair-preview-step"
          >
            {displayed ? "刷新本步预览" : "预览本步执行计划"}
          </Button>
          {preview.isPending && (
            <p role="status" data-testid="repair-preview-pending">
              正在重新冻结本步计划，确认入口已暂停。
            </p>
          )}
          {displayed && matches && <ExecutionPreview preview={displayed} />}
          {(needsApproximationConsent || acceptApproximations) && (
            <label>
              <Checkbox
                checked={acceptApproximations}
                disabled={busy}
                onChange={(event) => {
                  const accepted = event.target.checked;
                  setAcceptApproximations(accepted);
                  setAcknowledged(false);
                  preview.mutate({ accept_approximations: accepted });
                }}
              />
              接受所列近似处理
            </label>
          )}
          {displayed && matches && supported && !approximationConfirmed && (
            <p className="flash" role="status" data-testid="repair-approximation-required">
              尚未取得明确接受近似处理的冻结计划。请核对所列差异，明确勾选接受并等待新预览；未接受前不能执行。
            </p>
          )}
          {displayed && (!matches || !supported) && (
            <p className="flash err" role="alert">
              本步计划与当前范围不符、缺少凭据或模型不支持。未开放执行，请核对配置并重新预览。
            </p>
          )}
          {displayed &&
            matches &&
            supported &&
            approximationConfirmed &&
            !preview.isPending &&
            !preview.isError && (
              <>
                <label>
                  <Checkbox
                    checked={acknowledged}
                    disabled={busy}
                    onChange={(event) => setAcknowledged(event.target.checked)}
                  />
                  我已核对本步实际模型、引用、提示词和范围，确认可能产生模型费用
                </label>
                <Button
                  tone="primary"
                  data-testid="repair-execute-step"
                  disabled={!acknowledged || busy}
                  onClick={() => {
                    if (
                      !executable ||
                      !matches ||
                      !supported ||
                      !approximationConfirmed ||
                      !acknowledged ||
                      !displayed
                    )
                      return;
                    submit(
                      {
                        input: {
                          expected_plan_fingerprint: displayed.plan.plan_fingerprint!,
                          expected_step_ordinal: displayed.step_ordinal,
                          accept_approximations: acceptApproximations,
                          idempotency_key: `repair-step:${globalThis.crypto.randomUUID()}`,
                        },
                        outcome: "unconfirmed",
                      },
                      false,
                    );
                  }}
                >
                  确认执行本步候选生成
                </Button>
              </>
            )}
        </>
      )}
      {(preview.isError || (displayed && (!matches || !supported) && !pending)) && (
        <p data-testid="repair-configuration-exits">
          <a href={`/projects/${encodeURIComponent(projectId)}/scenes`}>
            前往分镜工作台修改镜头引用
          </a>
          {" · "}
          <a
            href={`/settings/projects/${encodeURIComponent(projectId)}?returnTo=${encodeURIComponent(`/projects/${projectId}/review?shotId=${shotId}`)}`}
          >
            修改本项目模型配置
          </a>
        </p>
      )}
      {request.next_action === "execute_step" && !repairCanPreviewStep(request) && !unknown && (
        <p className="flash" role="status">
          步骤事实尚未满足执行条件。请刷新状态，先审核并采用本步的正式关键帧。
        </p>
      )}
      {request.next_action === "ready_to_close" && !unknown && (
        <Button
          tone="primary"
          disabled={!closable}
          onClick={() => close.mutate("completed")}
          data-testid="repair-complete"
        >
          完成本次修复
        </Button>
      )}
      <Button
        tone="ghost"
        disabled={!closable}
        onClick={() => close.mutate("abandoned")}
        data-testid="repair-abandon"
      >
        放弃本次修复，重新定计划
      </Button>
      <p className="muted">放弃只结束本次修复流程，不取消远端任务，也不删除已有候选或正式素材。</p>
      {feedback && (
        <p className="muted" role="status" data-testid="repair-feedback">
          {feedback}
        </p>
      )}
    </div>
  );
}

function RepairPanelContent({ projectId, shotId, onClose }: RepairPlanPanelProps) {
  const queryClient = useQueryClient();
  const [option, setOption] = useState<RepairOption | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const confirmKey = useRef(`repair:${globalThis.crypto.randomUUID()}`);
  const enabled = Boolean(projectId) && Boolean(shotId);
  const repairs = useQuery({
    queryKey: queryKeys.review.repairs(projectId, shotId),
    queryFn: () => listRepairs(projectId, shotId),
    enabled,
    retry: false,
    refetchOnMount: "always",
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.closed_reason === null) ? 4000 : false,
  });
  const active = repairs.data?.find((item) => item.closed_reason === null) ?? null;
  const history = repairs.data?.filter((item) => item.closed_reason !== null) ?? [];
  const plan = useQuery({
    queryKey: queryKeys.review.repairPlan(projectId, shotId),
    queryFn: () => fetchRepairPlan(projectId, shotId),
    enabled: enabled && repairs.isSuccess && !active,
    retry: false,
  });
  const selected = active?.option ?? option ?? plan.data?.suggested_option ?? "rerun_video";

  function receive(request: RepairRequestRead) {
    queryClient.setQueryData<RepairRequestRead[]>(
      queryKeys.review.repairs(projectId, shotId),
      (previous) => [request, ...(previous ?? []).filter((item) => item.id !== request.id)],
    );
    if (request.closed_reason !== null) {
      confirmKey.current = `repair:${globalThis.crypto.randomUUID()}`;
      setFeedback(
        request.closed_reason === "completed"
          ? "本次修复已完成，历史已保留。"
          : "本次修复已放弃，可重新定计划；历史已保留。",
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.review.repairPlan(projectId, shotId),
      });
    }
  }
  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.review.repairs(projectId, shotId) });
  }
  const confirm = useMutation({
    mutationFn: () => {
      if (!plan.data || !repairs.isSuccess) throw new Error("修复计划尚未加载");
      return createRepair(projectId, shotId, {
        repair_option: selected,
        plan_hash: plan.data.plan_hash,
        idempotency_key: confirmKey.current,
      });
    },
    retry: false,
    onSuccess: (created) => {
      confirmKey.current = `repair:${globalThis.crypto.randomUUID()}`;
      setFeedback("已确认修复计划；请先预览本步，再显式确认生成。");
      receive(created);
      refresh();
    },
    onError: () => {
      setFeedback("确认修复失败。已刷新计划和修复记录，请核对后再确认；不会自动执行生成。");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.review.repairPlan(projectId, shotId),
      });
      refresh();
    },
  });

  return (
    <section className="qc-repair-panel" data-testid="repair-plan-panel">
      <header>
        <h3>修复计划</h3>
        {onClose && (
          <Button tone="ghost" onClick={onClose} data-testid="repair-close">
            关闭面板
          </Button>
        )}
      </header>
      {repairs.isPending && <p role="status">正在读取修复记录…</p>}
      {repairs.isError && (
        <p className="flash err" role="alert" data-testid="repair-list-error">
          无法读取当前修复状态，已暂停创建及执行；不会把读取失败当成没有修复。
          <Button onClick={refresh}>重新读取</Button>
        </p>
      )}
      {!active && plan.isError && (
        <p className="flash err" data-testid="repair-plan-error" role="alert">
          无法读取修复计划。<Button onClick={() => void plan.refetch()}>重新预览</Button>
        </p>
      )}
      {!active && repairs.isSuccess && plan.isPending && <p role="status">正在预览修复方案…</p>}
      {!active && repairs.isSuccess && plan.data && (
        <>
          <p className="muted" data-testid="repair-plan-summary">
            当前问题：{plan.data.annotation_count} 条待处理标注 · 本方案范围：
            {selected === "rerun_video" ? "仅视频" : "关键帧及视频"} · 保留素材：
            {plan.data.retained_assets.join("、") || "无"}
          </p>
          <p className="muted" data-testid="repair-plan-cost">
            {plan.data.cost_estimate_note}
          </p>
          <fieldset data-testid="repair-options" disabled={confirm.isPending}>
            <legend>修复选项</legend>
            {plan.data.repair_options.map((value) => (
              <label key={value}>
                <Input
                  type="radio"
                  name={`repair-option-${shotId}`}
                  value={value}
                  checked={selected === value}
                  onChange={() => {
                    setOption(value);
                    confirmKey.current = `repair:${globalThis.crypto.randomUUID()}`;
                  }}
                />
                {REPAIR_OPTION_LABEL[value]}
              </label>
            ))}
          </fieldset>
          <ol data-testid="repair-plan-steps">
            {REPAIR_OPTION_STAGES[selected].map((stage) => (
              <li key={stage}>{repairStageLabel(stage)}</li>
            ))}
          </ol>
          <Button
            tone="primary"
            data-testid="repair-confirm"
            disabled={
              !enabled || confirm.isPending || plan.isFetching || plan.isError || repairs.isFetching
            }
            onClick={() => confirm.mutate()}
          >
            确认修复计划
          </Button>
        </>
      )}
      {active && (
        <ActiveRepair
          key={active.id}
          projectId={projectId}
          shotId={shotId}
          request={active}
          readable={repairs.isSuccess && !repairs.isFetching}
          onRead={receive}
          onRefresh={refresh}
        />
      )}
      {history.length > 0 && (
        <details data-testid="repair-history">
          <summary>历史修复（{history.length}）</summary>
          {history.map((request) => (
            <section key={request.id}>
              <p>
                {REPAIR_OPTION_LABEL[request.option]} ·{" "}
                {request.closed_reason === "completed" ? "已完成" : "已结束"} · {request.created_at}
              </p>
              <StepHistory projectId={projectId} shotId={shotId} request={request} />
            </section>
          ))}
        </details>
      )}
      {feedback && (
        <p className="muted" data-testid="repair-plan-feedback" role="status">
          {feedback}
        </p>
      )}
      <p className="muted">
        修复不会自动覆盖正式版本，也不会自动关闭标注。关闭面板不代表取消运行或结束修复。
      </p>
    </section>
  );
}

/** Changing shot/workspace must not reuse another repair's preview or confirmation. */
export function RepairPlanPanel(props: RepairPlanPanelProps) {
  return (
    <RepairPanelContent
      key={JSON.stringify([getSelectedWorkspaceId(), props.projectId, props.shotId])}
      {...props}
    />
  );
}
