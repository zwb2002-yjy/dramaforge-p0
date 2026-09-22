import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";

import { queryKeys } from "../../lib/queryKeys";
import { ApiError, getExecutionModelPreflight, listModels } from "../../lib/api";
import {
  capabilityGapReason,
  capabilityGapSeverityLabel,
  executionModelLabel,
  referenceDeliveryLabel,
} from "../../lib/executionPlanLabels";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import {
  executionModelBlockerLabel,
  executionModelSourceLabel,
} from "../../lib/modelResolutionLabels";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import {
  activeStageStatus,
  stageOutcomeUnknown,
  stageQueueEstimate,
} from "../production/sceneRunState";
import { fetchDirectorCapabilities } from "../director/api";
import {
  delegateShotExecutionToDirector,
  fetchShotExecutionReceipt,
  previewShotExecution,
  shotExecutionIdempotencyKey,
  submitShotExecution,
  type PreparedShotExecution,
  type ShotExecutionRead,
  type ShotExecutionInput,
  type ShotExecutionPlanRead,
  type ShotExecutionStage,
  type ShotExecutionReference,
  type ShotLite,
} from "./api";
import {
  clearProductionOperation,
  productionOperationScope,
  readProductionOperation,
  recordProductionOperation,
} from "./productionOperationStore";

type ShotProductionActionsProps = {
  projectId: string;
  shot: ShotLite;
  references?: ShotExecutionReference[];
  referencesReady?: boolean;
  /** Block production until the selected Shot design has been persisted. */
  dirty?: boolean;
  /** Newest-first server NodeRun summary for this Shot. */
  trace?: unknown[];
  onExecuted?: (result: ShotExecutionRead) => void | Promise<void>;
  onDirectorDelegated?: () => void;
  onOpenDetails?: () => void;
};

type ActionFeedback = {
  kind: "success" | "error" | "plan";
  stage: ShotExecutionStage;
  message: string;
  nodeRunId?: string;
};

type PrepareOutcome = {
  stage: ShotExecutionStage;
  prepared: PreparedShotExecution;
  execution?: ShotExecutionRead;
};

const STAGE_LABEL: Record<ShotExecutionStage, string> = {
  image_keyframe: "关键帧",
  video: "视频",
};

const STAGE_MODE: Record<ShotExecutionStage, string> = {
  image_keyframe: "text_to_image",
  video: "first_frame",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Terminal NodeRun statuses: no further receipt polling is useful. */
const TERMINAL_EXECUTION_STATUSES = new Set([
  "completed",
  "cached",
  "completed_after_cancel",
  "failed",
  "blocked",
  "cancelled",
  "timed_out",
  "skipped",
  "rejected",
]);

/**
 * Clear a recorded operation when the submission provably ended.
 *
 * A rejection from the server (4xx) means no command was accepted; a terminal
 * NodeRun status means the command already finished. Anything else (network
 * failure, 5xx, timeout) leaves the record in place, because the operation may
 * have reached the server and reopening the page is the only way to adopt it.
 */
function submissionProvablyEnded(error: unknown, status?: string): boolean {
  if (status && TERMINAL_EXECUTION_STATUSES.has(status)) return true;
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return true;
  return false;
}

function serverStatusLabel(status: string): string {
  return nodeRunStatusLabel(status);
}

function planDelivery(preview: ShotExecutionPlanRead): "exact" | "approximate" | "unsupported" {
  const references = preview.plan.planned_references ?? [];
  const gaps = preview.plan.capability_gaps ?? [];
  if (references.some((reference) => reference.delivery === "unsupported")) return "unsupported";
  if (gaps.some((gap) => gap.severity === "fatal")) return "unsupported";
  if (references.some((reference) => reference.delivery === "approximate")) return "approximate";
  if (gaps.some((gap) => gap.severity === "warning")) return "approximate";
  return "exact";
}

function stablePlanIdentity(preview: ShotExecutionPlanRead): string {
  return JSON.stringify({
    project_id: preview.plan.project_id,
    shot_id: preview.plan.shot_id,
    stage: preview.plan.stage,
    prompt: preview.plan.prompt,
    semantic_intent: preview.plan.semantic_intent,
    mode_id: preview.plan.mode_id,
    resolved_model: preview.plan.resolved_model,
    planned_references: preview.plan.planned_references,
    expected_shot_version: preview.plan.expected_shot_version,
    connection_revision_id: preview.plan.connection_revision_id,
    credential_revision_id: preview.plan.credential_revision_id,
  });
}

/**
 * The selected-shot production controls for the canonical Workbench path.
 *
 * A click first asks the backend to freeze an execution plan and then submits
 * that exact fingerprint.  This component never chooses an artifact for video
 * and never promotes a queued run to a successful result in local state.
 */
export function ShotProductionActions({
  projectId,
  shot,
  references = [],
  referencesReady = true,
  dirty = false,
  trace = [],
  onExecuted,
  onDirectorDelegated,
  onOpenDetails,
}: ShotProductionActionsProps) {
  const queryClient = useQueryClient();
  const delegationDecisionIds = useRef(new Map<string, string>());
  // Deployment-level engine facts. A failed read must not hide the manual path:
  // manual generation never depends on the Director runtime.
  const capabilities = useQuery({
    queryKey: queryKeys.director.capabilities(projectId),
    queryFn: () => fetchDirectorCapabilities(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
    retry: false,
  });
  const directorCapabilities = capabilities.data ?? null;
  // Display names for execution models come from the backend catalogue; the raw
  // `provider/model` id is contract data and never rendered on this surface.
  const models = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
    enabled: Boolean(projectId) && projectId !== "demo",
    retry: false,
  });
  const modelPreflight = useQuery({
    queryKey: queryKeys.model.executionPreflight(projectId),
    queryFn: () => getExecutionModelPreflight(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
    retry: false,
  });
  // Only an explicit `runtime_turns_available === false` closes the AUTO entry
  // point. A failed, in-flight or malformed read must not disable it: the server
  // re-validates every submission anyway, and a read model must never remove a
  // working action.
  const directorDelegateBlocked = directorCapabilities?.runtime_turns_available === false;
  const [feedback, setFeedback] = useState<ActionFeedback | null>(null);
  const [displayedPlan, setDisplayedPlan] = useState<ShotExecutionPlanRead | null>(null);
  const [pendingApproximation, setPendingApproximation] = useState<PreparedShotExecution | null>(
    null,
  );
  const [planFailure, setPlanFailure] = useState<"unsupported" | null>(null);

  useEffect(() => {
    setFeedback(null);
    setDisplayedPlan(null);
    setPendingApproximation(null);
    setPlanFailure(null);
  }, [shot.id]);

  /**
   * Adopt a submission this browser already sent.
   *
   * A reload (or a lost response followed by reopening the page) keeps the
   * command key in storage, so the UI asks the server for that same command's
   * receipt: an operation that did reach the server is shown as running instead
   * of being submitted a second time. A 404 answer only means "no committed
   * receipt yet" and never triggers a new key.
   */
  useEffect(() => {
    let cancelled = false;
    const stages: ShotExecutionStage[] = ["image_keyframe", "video"];
    for (const stage of stages) {
      const scope = productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, stage);
      const operation = readProductionOperation(scope);
      if (!operation) continue;
      void fetchShotExecutionReceipt(projectId, shot.id, stage, operation.operationKey)
        .then((receipt) => {
          if (cancelled || !receipt) return;
          if (TERMINAL_EXECUTION_STATUSES.has(receipt.status)) {
            clearProductionOperation(scope);
          }
          setFeedback({
            kind: "success",
            stage,
            message: receipt.status,
            nodeRunId: receipt.node_run_id,
          });
        })
        .catch(() => {
          // Recovery stays best effort; the action buttons surface real errors.
        });
    }
    return () => {
      cancelled = true;
    };
  }, [projectId, shot.id]);

  function executionInput(stage: ShotExecutionStage): ShotExecutionInput {
    const configuredPrompt =
      stage === "image_keyframe" ? (shot.image_prompt ?? "") : (shot.video_prompt ?? "");
    const prompt = configuredPrompt.trim() || (shot.visual_description ?? "").trim();
    if (!prompt) {
      throw new Error(`请先填写${STAGE_LABEL[stage]}提示词`);
    }
    return {
      stage,
      prompt,
      // Creative semantics are reconstructed from saved server facts. The
      // browser sends no draft/canonical duplicate.
      semantic_intent: {},
      mode_id: STAGE_MODE[stage],
      requested_model_id: null,
      requested_binding_id: null,
      accept_approximations: false,
      references: references.map((reference) => ({ ...reference })),
      expected_shot_version: shot.version,
    };
  }

  async function refreshAfterExecution(result: ShotExecutionRead): Promise<void> {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.scene.workspace(projectId, shot.scene_id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.scene.summaries(projectId),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.shot.productionTrace(projectId, shot.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.shot.workbench(projectId, shot.id),
      }),
    ]);
    await onExecuted?.(result);
  }

  const produce = useMutation<PrepareOutcome, unknown, ShotExecutionStage>({
    mutationFn: async (stage) => {
      if (dirty) {
        // The disabled attribute is the normal UI path; keep the same guard
        // in the mutation so an imperative/event-level trigger cannot bypass
        // the unsaved-design production gate.
        throw new Error("请先保存镜头设计，再生成关键帧或视频。");
      }
      const input = executionInput(stage);
      const preview = await previewShotExecution(projectId, shot.id, input);
      const prepared: PreparedShotExecution = {
        input,
        preview,
        // Derived from the frozen plan, never from a random nonce: a retry of
        // this exact plan keeps one command identity instead of billing again.
        idempotencyKey: shotExecutionIdempotencyKey(shot.id, preview.plan_fingerprint),
      };
      if (planDelivery(preview) === "approximate") return { stage, prepared };
      // Persist the operation identity before the request leaves the browser so
      // a reload can still adopt this same command.
      recordProductionOperation(
        productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, stage),
        {
          operationKey: prepared.idempotencyKey,
          planFingerprint: prepared.preview.plan_fingerprint,
          stage,
          recordedAt: new Date().toISOString(),
          nodeRunId: null,
        },
      );
      const execution = await submitShotExecution(projectId, shot.id, prepared);
      return { stage, prepared, execution };
    },
    onMutate: (stage) => {
      setFeedback(null);
      return { stage };
    },
    onSuccess: async ({ stage, prepared, execution }) => {
      setDisplayedPlan(prepared.preview);
      setPlanFailure(null);
      if (!execution) {
        setPendingApproximation(prepared);
        setFeedback({ kind: "plan", stage, message: "approximate" });
        return;
      }
      setPendingApproximation(null);
      if (submissionProvablyEnded(null, execution.status)) {
        clearProductionOperation(
          productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, stage),
        );
      }
      setFeedback({
        kind: "success",
        stage,
        message: execution.status,
        nodeRunId: execution.node_run_id,
      });
      await refreshAfterExecution(execution);
    },
    onError: (error, stage) => {
      // Preserve the backend's real message (not a client-side success or a
      // guessed "no formal keyframe" state).  In particular, a video request
      // without a formal keyframe is rejected by the Workbench plan builder.
      const message = errorMessage(error);
      if (submissionProvablyEnded(error)) {
        clearProductionOperation(
          productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, stage),
        );
      }
      setDisplayedPlan(null);
      setPendingApproximation(null);
      setPlanFailure(/unsupported|capability gap/i.test(message) ? "unsupported" : null);
      setFeedback({ kind: "error", stage, message });
    },
  });

  const confirmApproximation = useMutation({
    mutationFn: async (prepared: PreparedShotExecution) => {
      const acceptedInput: ShotExecutionInput = {
        ...prepared.input,
        accept_approximations: true,
      };
      const acceptedPreview = await previewShotExecution(projectId, shot.id, acceptedInput);
      if (stablePlanIdentity(acceptedPreview) !== stablePlanIdentity(prepared.preview)) {
        throw new Error("模型、引用或创作意图在确认期间已变化，请重新生成并确认计划。");
      }
      // The accepted plan is a different frozen plan, so it carries its own
      // command identity; the discovery preview is never submitted.
      const accepted: PreparedShotExecution = {
        ...prepared,
        input: acceptedInput,
        preview: acceptedPreview,
        idempotencyKey: shotExecutionIdempotencyKey(shot.id, acceptedPreview.plan_fingerprint),
      };
      recordProductionOperation(
        productionOperationScope(
          getSelectedWorkspaceId(),
          projectId,
          shot.id,
          prepared.input.stage,
        ),
        {
          operationKey: accepted.idempotencyKey,
          planFingerprint: accepted.preview.plan_fingerprint,
          stage: prepared.input.stage,
          recordedAt: new Date().toISOString(),
          nodeRunId: null,
        },
      );
      return {
        prepared: accepted,
        execution: await submitShotExecution(projectId, shot.id, accepted),
      };
    },
    onSuccess: async ({ prepared, execution }) => {
      setDisplayedPlan(prepared.preview);
      setPendingApproximation(null);
      setPlanFailure(null);
      if (submissionProvablyEnded(null, execution.status)) {
        clearProductionOperation(
          productionOperationScope(
            getSelectedWorkspaceId(),
            projectId,
            shot.id,
            prepared.input.stage,
          ),
        );
      }
      setFeedback({
        kind: "success",
        stage: prepared.input.stage,
        message: execution.status,
        nodeRunId: execution.node_run_id,
      });
      await refreshAfterExecution(execution);
    },
    onError: (error) => {
      const stage = pendingApproximation?.input.stage ?? "image_keyframe";
      if (submissionProvablyEnded(error)) {
        clearProductionOperation(
          productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, stage),
        );
      }
      setPendingApproximation(null);
      setFeedback({ kind: "error", stage, message: errorMessage(error) });
    },
  });

  const delegate = useMutation({
    mutationFn: async (stage: ShotExecutionStage) => {
      if (dirty) throw new Error("请先保存镜头设计，再委托导演执行。");
      if (directorDelegateBlocked) {
        // The server re-validates; this only avoids offering a guaranteed 409.
        throw new Error(directorCapabilities?.blocker_message ?? "当前部署未启用自动导演运行时。");
      }
      const input = executionInput(stage);
      const preview = await previewShotExecution(projectId, shot.id, input);
      if (planDelivery(preview) !== "exact") {
        throw new Error("当前计划需要近似适配确认，请先使用手动生成入口检查并确认。");
      }
      const decisionKey = `${shot.id}:${stage}:${preview.plan_fingerprint}`;
      let decisionId = delegationDecisionIds.current.get(decisionKey);
      if (!decisionId) {
        decisionId = globalThis.crypto.randomUUID();
        delegationDecisionIds.current.set(decisionKey, decisionId);
      }
      const turn = await delegateShotExecutionToDirector(projectId, shot.id, {
        input,
        preview,
        decisionId,
      });
      return { stage, turn, decisionKey };
    },
    onMutate: () => setFeedback(null),
    onSuccess: async ({ stage, decisionKey }) => {
      delegationDecisionIds.current.delete(decisionKey);
      setFeedback({ kind: "success", stage, message: "director_queued" });
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.director.turns(projectId, "shot", shot.id),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.scene.workspace(projectId, shot.scene_id),
        }),
      ]);
      onDirectorDelegated?.();
    },
    onError: (error, stage) => {
      setFeedback({ kind: "error", stage, message: errorMessage(error) });
    },
  });

  const activeStage = produce.isPending
    ? produce.variables
    : delegate.isPending
      ? delegate.variables
      : confirmApproximation.isPending
        ? (pendingApproximation?.input.stage ?? null)
        : null;
  const keyframeStatus = activeStageStatus(trace, "image_keyframe");
  const videoStatus = activeStageStatus(trace, "video");
  const keyframeOutcomeUnknown = stageOutcomeUnknown(trace, "image_keyframe");
  const videoOutcomeUnknown = stageOutcomeUnknown(trace, "video");
  const keyframeQueue = stageQueueEstimate(trace, "image_keyframe");
  const videoQueue = stageQueueEstimate(trace, "video");
  const delivery = displayedPlan ? planDelivery(displayedPlan) : planFailure;
  const plannedReferences = displayedPlan?.plan.planned_references ?? [];
  // The stored id stays a contract value; the surface shows the catalogue's
  // display name and keeps the id in the collapsed diagnostics block.
  const planModel = executionModelLabel(
    displayedPlan?.plan.resolved_model?.resolved_model_id,
    Array.isArray(models.data) ? models.data : undefined,
  );
  const preflightStage = (stage: ShotExecutionStage) =>
    (Array.isArray(modelPreflight.data?.stages)
      ? modelPreflight.data.stages.find((item) => item.stage === stage)
      : null) ?? null;
  const keyframePreflight = preflightStage("image_keyframe");
  const videoPreflight = preflightStage("video");
  const preflightBlocks = (stage: ShotExecutionStage) => {
    if (projectId === "demo") return false;
    if (modelPreflight.isPending || modelPreflight.isError) return true;
    return preflightStage(stage)?.ready !== true;
  };

  const buttonLabel = (stage: ShotExecutionStage, serverStatus: string | null) => {
    const label = STAGE_LABEL[stage];
    if (stage === "image_keyframe" && keyframeOutcomeUnknown) return `${label}提交结果待对账`;
    if (stage === "video" && videoOutcomeUnknown) return `${label}提交结果待对账`;
    if (activeStage === stage) return `${label}请求提交中…`;
    if (serverStatus === "queued") return `${label}已排队`;
    if (serverStatus === "cancel_requested") return `${label}取消中…`;
    if (serverStatus === "running") return `${label}生成中…`;
    return `生成${label}`;
  };

  return (
    <section
      className="qc-shot-production-actions"
      data-testid="shot-production-actions"
      data-shot-id={shot.id}
    >
      <header>
        <div>
          <span className="director-stage-kicker">当前镜头</span>
          <strong>#{shot.shot_number} 生成</strong>
        </div>
      </header>

      <dl className="qc-shot-production-lineage">
        <dt>正式关键帧</dt>
        <dd>{shot.formal_keyframe_artifact_id ? "已选择" : "未选择"}</dd>
        <dt>正式视频</dt>
        <dd>{shot.formal_video_artifact_id ? "已选择" : "未选择"}</dd>
      </dl>

      <section
        className="qc-shot-production-plan"
        data-testid="shot-production-preflight"
        aria-label="生产模型预检"
      >
        <strong>生产前预检</strong>
        {modelPreflight.isPending ? (
          <p role="status">正在解析实际执行模型…</p>
        ) : modelPreflight.isError ? (
          <p role="alert">无法读取生产模型预检；为避免错误提交，生成入口已暂停。</p>
        ) : (
          <dl className="qc-shot-production-lineage">
            {(
              [
                ["关键帧", keyframePreflight],
                ["视频", videoPreflight],
              ] as const
            ).map(([label, item]) => (
              <div key={label} data-testid={`production-preflight-${item?.stage ?? label}`}>
                <dt>{label}</dt>
                <dd>
                  {item?.ready && item.resolved_model_id ? (
                    <>
                      {
                        executionModelLabel(
                          item.resolved_model_id,
                          Array.isArray(models.data) ? models.data : undefined,
                        ).label
                      }
                      {` · ${executionModelSourceLabel(item.source)}`}
                    </>
                  ) : (
                    <>不可执行 · {executionModelBlockerLabel(item?.reason)}</>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <div className="qc-shot-production-buttons">
        <button
          type="button"
          data-testid="generate-keyframe"
          onClick={() => produce.mutate("image_keyframe")}
          disabled={
            produce.isPending ||
            delegate.isPending ||
            confirmApproximation.isPending ||
            Boolean(pendingApproximation) ||
            Boolean(keyframeStatus) ||
            keyframeOutcomeUnknown ||
            !referencesReady ||
            dirty ||
            preflightBlocks("image_keyframe")
          }
        >
          {buttonLabel("image_keyframe", keyframeStatus)}
        </button>
        <button
          type="button"
          data-testid="generate-video"
          onClick={() => produce.mutate("video")}
          disabled={
            produce.isPending ||
            delegate.isPending ||
            confirmApproximation.isPending ||
            Boolean(pendingApproximation) ||
            Boolean(videoStatus) ||
            videoOutcomeUnknown ||
            !referencesReady ||
            dirty ||
            !shot.formal_keyframe_artifact_id ||
            preflightBlocks("video")
          }
        >
          {buttonLabel("video", videoStatus)}
        </button>
      </div>

      <div className="qc-shot-production-buttons">
        <button
          type="button"
          className="secondary"
          data-testid="delegate-keyframe-to-director"
          onClick={() => delegate.mutate("image_keyframe")}
          disabled={
            produce.isPending ||
            delegate.isPending ||
            confirmApproximation.isPending ||
            Boolean(pendingApproximation) ||
            Boolean(keyframeStatus) ||
            keyframeOutcomeUnknown ||
            directorDelegateBlocked ||
            !referencesReady ||
            dirty ||
            preflightBlocks("image_keyframe")
          }
        >
          导演执行关键帧（AUTO）
        </button>
        <button
          type="button"
          className="secondary"
          data-testid="delegate-video-to-director"
          onClick={() => delegate.mutate("video")}
          disabled={
            produce.isPending ||
            delegate.isPending ||
            confirmApproximation.isPending ||
            Boolean(pendingApproximation) ||
            Boolean(videoStatus) ||
            videoOutcomeUnknown ||
            directorDelegateBlocked ||
            !referencesReady ||
            dirty ||
            !shot.formal_keyframe_artifact_id ||
            preflightBlocks("video")
          }
        >
          导演执行视频（AUTO）
        </button>
      </div>

      {directorDelegateBlocked && (
        <p
          className="qc-shot-production-hint"
          data-testid="shot-production-director-blocked"
          role="status"
        >
          {directorCapabilities?.blocker_message}
        </p>
      )}

      <p className="qc-shot-production-hint">
        {shot.formal_keyframe_artifact_id
          ? "视频只使用后端确认的正式关键帧，不会自动改用其他图片。"
          : "生成视频已暂停：请先审查候选并设置正式关键帧。"}
      </p>
      {!referencesReady && (
        <p className="qc-shot-production-hint" role="status">
          正在解析当前镜头的资产引用；解析完成前不会提交生产请求。
        </p>
      )}
      {(keyframeStatus || videoStatus) && (
        <p className="qc-shot-production-hint" data-testid="shot-production-running" role="status">
          服务端任务仍在执行；页面会自动同步，当前阶段不会重复提交。
        </p>
      )}
      {(keyframeQueue || videoQueue) && (
        <p className="qc-shot-production-hint" data-testid="shot-production-queue" role="status">
          {(
            [
              keyframeQueue ? (["关键帧", keyframeQueue] as const) : null,
              videoQueue ? (["视频", videoQueue] as const) : null,
            ].filter(Boolean) as Array<readonly [string, NonNullable<typeof keyframeQueue>]>
          )
            .map(([label, queue]) => {
              const wait =
                queue.estimatedWaitSeconds === null
                  ? "等待时间仍在学习"
                  : `预计等待约 ${Math.max(1, Math.ceil(queue.estimatedWaitSeconds / 60))} 分钟`;
              return `${label}在本作品待执行序位第 ${queue.position} 位，前方 ${queue.ahead} 项，${wait}`;
            })
            .join("；")}
          。仅按本作品服务端记录估算，不代表 Provider 全局队列。
        </p>
      )}
      {(keyframeOutcomeUnknown || videoOutcomeUnknown) && (
        <p
          className="qc-shot-production-hint"
          data-testid="shot-production-outcome-unknown"
          role="status"
        >
          上次提交结果不明，已暂停本阶段，避免重复计费。请按原操作键对账并核对供应商原任务回执；没有远端任务
          ID 时，需要供应商协助查单，不能直接重试。
          {onOpenDetails && (
            <button type="button" className="secondary" onClick={onOpenDetails}>
              查看待对账执行记录
            </button>
          )}
        </p>
      )}
      {dirty && (
        <p className="qc-shot-production-hint" data-testid="shot-production-unsaved" role="status">
          请先保存镜头设计，再生成关键帧或视频。
        </p>
      )}

      {delivery && (
        <section
          className="qc-shot-production-plan"
          data-testid="shot-execution-plan-preview"
          data-delivery={delivery}
        >
          <strong>模型适配：{referenceDeliveryLabel(delivery)}</strong>
          {displayedPlan && (
            <>
              <p data-testid="shot-execution-plan-model">执行模型：{planModel.label}</p>
              <p data-testid="shot-execution-plan-references">
                引用：完全支持 {plannedReferences.filter((row) => row.delivery === "exact").length}{" "}
                · 近似支持{" "}
                {plannedReferences.filter((row) => row.delivery === "approximate").length} · 不支持{" "}
                {plannedReferences.filter((row) => row.delivery === "unsupported").length}
              </p>
              {(displayedPlan.plan.capability_gaps ?? []).map((gap, index) => {
                const gapReason = capabilityGapReason(gap.reason);
                return (
                  <p key={`${gap.severity}-${index}`} className="qc-shot-production-hint">
                    {capabilityGapSeverityLabel(gap.severity)}：{gapReason.label}
                    {(gap.controls ?? []).length ? `（${(gap.controls ?? []).join("、")}）` : ""}
                  </p>
                );
              })}
              <details
                className="editing-diagnostics"
                data-testid="shot-execution-plan-diagnostics"
              >
                <summary>开发 / 诊断详情（只读）</summary>
                <small>
                  适配 {delivery} · 模型 {planModel.raw || "无"}
                  {(displayedPlan.plan.capability_gaps ?? [])
                    .map(
                      (gap) =>
                        ` · ${gap.severity} ${gap.capability ?? ""}${
                          gap.reason ? ` ${gap.reason}` : ""
                        }`,
                    )
                    .join("")}
                </small>
              </details>
              {(displayedPlan.plan.pending_suggestions ?? []).length > 0 && (
                <div
                  className="qc-shot-production-hint"
                  data-testid="shot-execution-plan-suggestions"
                  role="note"
                >
                  <p>
                    <strong>建议（尚未生效）：</strong>
                    以下内容来自项目创作档案或模板推荐，本次执行不会使用它们，也不作为 Provider
                    硬参数下发。
                  </p>
                  <ul>
                    {(displayedPlan.plan.pending_suggestions ?? []).map((suggestion) => (
                      <li key={suggestion.key} data-testid={`plan-suggestion-${suggestion.key}`}>
                        {suggestion.label}：{suggestion.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
          {pendingApproximation && (
            <div className="qc-shot-production-buttons">
              <button
                type="button"
                data-testid="confirm-shot-execution-approximation"
                disabled={confirmApproximation.isPending}
                onClick={() => confirmApproximation.mutate(pendingApproximation)}
              >
                {confirmApproximation.isPending ? "正在重新校验…" : "确认近似适配并执行"}
              </button>
              <button
                type="button"
                className="secondary"
                data-testid="cancel-shot-execution-approximation"
                disabled={confirmApproximation.isPending}
                onClick={() => {
                  setPendingApproximation(null);
                  setFeedback(null);
                }}
              >
                取消
              </button>
            </div>
          )}
        </section>
      )}

      {feedback?.kind === "success" && (
        <p
          className="qc-shot-production-status"
          data-testid="shot-production-status"
          data-status={feedback.message}
          role="status"
        >
          {feedback.message === "director_queued" ? (
            <>{STAGE_LABEL[feedback.stage]}已授权给导演执行；正在切换到导演状态。</>
          ) : (
            <>
              {STAGE_LABEL[feedback.stage]}请求已提交，服务器状态：
              {serverStatusLabel(feedback.message)}。镜头 {shot.id}
              {feedback.nodeRunId ? `，任务 ${feedback.nodeRunId}` : ""}。完成后请比较候选并审查。
            </>
          )}
        </p>
      )}
      {feedback?.kind === "error" && (
        <p className="qc-shot-production-error" data-testid="shot-production-error" role="alert">
          {/MODEL_BINDING_MISSING/.test(feedback.message) ? (
            <>
              尚未为此项目选择{STAGE_LABEL[feedback.stage]}模型。
              <Link
                to="/settings/projects/$projectId"
                params={{ projectId }}
                search={{
                  returnTo: `/projects/${projectId}/scenes/${shot.scene_id}?shotId=${shot.id}`,
                }}
              >
                配置本项目模型
              </Link>
              。保存后返回这里继续，刚才的检查没有提交生成。
            </>
          ) : (
            <>
              {STAGE_LABEL[feedback.stage]}生成失败：{feedback.message}
            </>
          )}
        </p>
      )}
    </section>
  );
}
