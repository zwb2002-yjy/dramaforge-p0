import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { queryKeys } from "../../lib/queryKeys";
import { activeStageStatus } from "../production/sceneRunState";
import {
  delegateShotExecutionToDirector,
  dispatchShotExecution,
  previewShotExecution,
  type PreparedShotExecution,
  type ShotExecutionRead,
  type ShotExecutionInput,
  type ShotExecutionPlanRead,
  type ShotExecutionStage,
  type ShotExecutionReference,
  type ShotLite,
} from "./api";

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
};

type ActionFeedback = {
  kind: "success" | "error" | "plan";
  stage: ShotExecutionStage;
  message: string;
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

function idempotencyKey(projectId: string, shotId: string, stage: ShotExecutionStage): string {
  const nonce = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`;
  // NodeRun uniqueness is already scoped by Project; repeating both UUIDs in
  // the header made the server's workbench prefix exceed VARCHAR(160).
  void projectId;
  void shotId;
  return `shot-production:${stage}:${nonce}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function serverStatusLabel(status: string): string {
  if (status === "queued") return "已排队";
  if (status === "running") return "处理中";
  if (status === "cancel_requested") return "取消中";
  return status;
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
}: ShotProductionActionsProps) {
  const queryClient = useQueryClient();
  const delegationDecisionIds = useRef(new Map<string, string>());
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
        idempotencyKey: idempotencyKey(projectId, shot.id, stage),
      };
      if (planDelivery(preview) === "approximate") return { stage, prepared };
      const execution = await dispatchShotExecution(projectId, shot.id, prepared);
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
      setFeedback({ kind: "success", stage, message: execution.status });
      await refreshAfterExecution(execution);
    },
    onError: (error, stage) => {
      // Preserve the backend's real message (not a client-side success or a
      // guessed "no formal keyframe" state).  In particular, a video request
      // without a formal keyframe is rejected by the Workbench plan builder.
      const message = errorMessage(error);
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
      return {
        prepared: {
          ...prepared,
          input: acceptedInput,
          preview: acceptedPreview,
        },
        execution: await dispatchShotExecution(projectId, shot.id, {
          ...prepared,
          input: acceptedInput,
          preview: acceptedPreview,
        }),
      };
    },
    onSuccess: async ({ prepared, execution }) => {
      setDisplayedPlan(prepared.preview);
      setPendingApproximation(null);
      setPlanFailure(null);
      setFeedback({ kind: "success", stage: prepared.input.stage, message: execution.status });
      await refreshAfterExecution(execution);
    },
    onError: (error) => {
      const stage = pendingApproximation?.input.stage ?? "image_keyframe";
      setPendingApproximation(null);
      setFeedback({ kind: "error", stage, message: errorMessage(error) });
    },
  });

  const delegate = useMutation({
    mutationFn: async (stage: ShotExecutionStage) => {
      if (dirty) throw new Error("请先保存镜头设计，再委托导演执行。");
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
  const delivery = displayedPlan ? planDelivery(displayedPlan) : planFailure;
  const plannedReferences = displayedPlan?.plan.planned_references ?? [];
  const resolvedModel = displayedPlan?.plan.resolved_model?.resolved_model_id ?? "未解析";

  const buttonLabel = (stage: ShotExecutionStage, serverStatus: string | null) => {
    const label = STAGE_LABEL[stage];
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
            !referencesReady ||
            dirty
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
            !referencesReady ||
            dirty
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
            !referencesReady ||
            dirty
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
            !referencesReady ||
            dirty
          }
        >
          导演执行视频（AUTO）
        </button>
      </div>

      <p className="qc-shot-production-hint">
        视频只使用后端确认的正式关键帧；未选择时由后端拒绝，不会自动改用其他图片。
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
          <strong>模型适配：{delivery}</strong>
          {displayedPlan && (
            <>
              <p data-testid="shot-execution-plan-model">模型：{resolvedModel}</p>
              <p data-testid="shot-execution-plan-references">
                引用 exact {plannedReferences.filter((row) => row.delivery === "exact").length} ·
                approximate
                {plannedReferences.filter((row) => row.delivery === "approximate").length} ·
                unsupported
                {plannedReferences.filter((row) => row.delivery === "unsupported").length}
              </p>
              {(displayedPlan.plan.capability_gaps ?? []).map((gap, index) => (
                <p key={`${gap.severity}-${index}`} className="qc-shot-production-hint">
                  {gap.severity}：{gap.reason}
                  {(gap.controls ?? []).length ? `（${(gap.controls ?? []).join("、")}）` : ""}
                </p>
              ))}
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
              {serverStatusLabel(feedback.message)}
            </>
          )}
        </p>
      )}
      {feedback?.kind === "error" && (
        <p className="qc-shot-production-error" data-testid="shot-production-error" role="alert">
          {STAGE_LABEL[feedback.stage]}生成失败：{feedback.message}
        </p>
      )}
    </section>
  );
}
