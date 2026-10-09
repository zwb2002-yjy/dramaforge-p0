import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Button, Disclosure, Field, Select } from "../../components/ui";

import { queryKeys } from "../../lib/queryKeys";
import { ApiError, getExecutionModelPreflight, listModels } from "../../lib/api";
import {
  capabilityGapReason,
  capabilityGapSeverityLabel,
  executionModelLabel,
  referenceDeliveryLabel,
} from "../../lib/executionPlanLabels";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import { executionModelBlockerLabel } from "../../lib/modelResolutionLabels";
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
  NEXT_ACTION_BLOCKER_LABEL,
  VIDEO_MODE_LABEL,
  defaultVideoMode,
  shotNextAction,
  type ShotVideoMode,
} from "./shotNextAction";
import { isConfirmableShotCandidate, type ShotCandidate } from "./shotCandidates";
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
  /** Saves the selected Shot design; the primary action when it is dirty. */
  onSave?: () => void;
  saving?: boolean;
  /** Parsed candidates of this Shot; drive the "检查候选" primary action. */
  candidates?: ShotCandidate[];
  onReviewCandidates?: () => void;
  /** Open model settings in a drawer without leaving the canvas. */
  onOpenModelSettings?: () => void;
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

/** Creator-facing stage nouns: a keyframe is "画面" on the shot surface. */
const STAGE_NOUN: Record<ShotExecutionStage, string> = {
  image_keyframe: "画面",
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
  onSave,
  saving = false,
  candidates = [],
  onReviewCandidates,
  onOpenModelSettings,
}: ShotProductionActionsProps) {
  const queryClient = useQueryClient();
  const delegationDecisionIds = useRef(new Map<string, string>());
  const lastFrameCount = references.filter(
    (reference) => reference.purpose === "last_frame",
  ).length;
  // The mode follows saved facts until the creator picks one explicitly.
  const [explicitMode, setExplicitMode] = useState<ShotVideoMode | null>(null);
  const videoMode =
    explicitMode ??
    defaultVideoMode({
      hasFormalKeyframe: Boolean(shot.formal_keyframe_artifact_id),
      lastFrameCount,
    });
  const pendingCandidates = (stage: ShotExecutionStage) =>
    candidates.filter(
      (candidate) =>
        candidate.stage === stage &&
        isConfirmableShotCandidate(candidate) &&
        candidate.reviewDecision !== "rejected",
    ).length;
  const referenceVideoCount = references.filter((reference) =>
    [
      "identity",
      "clothing",
      "pose",
      "style",
      "scene_layout",
      "scene_lighting",
      "generic_reference",
      "action",
      "camera_language",
      "audio_rhythm",
    ].includes(reference.purpose),
  ).length;
  // Deployment-level engine facts. A failed read must not hide the manual path:
  // manual generation never depends on the Director runtime.
  const capabilities = useQuery({
    queryKey: queryKeys.director.capabilities(projectId),
    queryFn: () => fetchDirectorCapabilities(projectId),
    enabled: Boolean(projectId),
    retry: false,
  });
  const directorCapabilities = capabilities.data ?? null;
  // Display names for execution models come from the backend catalogue; the raw
  // `provider/model` id is contract data and never rendered on this surface.
  const models = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
    enabled: Boolean(projectId),
    retry: false,
  });
  const modelPreflight = useQuery({
    queryKey:
      videoMode === "first_frame"
        ? queryKeys.model.executionPreflight(projectId)
        : [...queryKeys.model.executionPreflight(projectId), videoMode],
    queryFn: () => getExecutionModelPreflight(projectId, videoMode),
    enabled: Boolean(projectId),
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
    setExplicitMode(null);
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
      mode_id: stage === "video" ? videoMode : STAGE_MODE[stage],
      requested_model_id: null,
      requested_binding_id: null,
      accept_approximations: false,
      references: (stage !== "video"
        ? references
        : videoMode === "text_to_video"
          ? []
          : videoMode === "last_frame" || videoMode === "first_last_frame"
            ? references.filter((reference) => reference.purpose === "last_frame")
            : videoMode === "omni_reference"
              ? references.filter(
                  (reference) => !["first_frame", "last_frame"].includes(reference.purpose),
                )
              : references
      ).map((reference) => ({ ...reference })),
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
    if (modelPreflight.isPending || modelPreflight.isError) return true;
    return preflightStage(stage)?.ready !== true;
  };

  const buttonLabel = (stage: ShotExecutionStage, serverStatus: string | null) => {
    const label = STAGE_NOUN[stage];
    if (stage === "image_keyframe" && keyframeOutcomeUnknown) return `${label}状态待同步`;
    if (stage === "video" && videoOutcomeUnknown) return `${label}状态待同步`;
    if (activeStage === stage) return "正在提交…";
    if (serverStatus === "queued") return `${label}排队中…`;
    if (serverStatus === "cancel_requested") return `${label}取消中…`;
    if (serverStatus === "running") return `${label}生成中…`;
    return stage === "image_keyframe"
      ? shot.formal_keyframe_artifact_id
        ? "重新生成画面"
        : "生成画面"
      : shot.formal_video_artifact_id
        ? "重新生成视频"
        : "生成视频";
  };

  const busy =
    produce.isPending ||
    delegate.isPending ||
    confirmApproximation.isPending ||
    Boolean(pendingApproximation);
  const keyframeDisabled =
    busy ||
    Boolean(keyframeStatus) ||
    keyframeOutcomeUnknown ||
    !referencesReady ||
    dirty ||
    preflightBlocks("image_keyframe");
  const videoDisabled =
    busy ||
    Boolean(videoStatus) ||
    videoOutcomeUnknown ||
    (videoMode !== "text_to_video" && !referencesReady) ||
    dirty ||
    (videoMode === "first_frame" && !shot.formal_keyframe_artifact_id) ||
    (videoMode === "first_last_frame" && !shot.formal_keyframe_artifact_id) ||
    ((videoMode === "last_frame" || videoMode === "first_last_frame") && lastFrameCount !== 1) ||
    (videoMode === "omni_reference" && referenceVideoCount === 0) ||
    preflightBlocks("video");

  const next = shotNextAction({
    dirty,
    hasFormalKeyframe: Boolean(shot.formal_keyframe_artifact_id),
    hasFormalVideo: Boolean(shot.formal_video_artifact_id),
    pendingKeyframeCandidates: pendingCandidates("image_keyframe"),
    pendingVideoCandidates: pendingCandidates("video"),
    keyframeStatus,
    videoStatus,
    keyframeUnknown: keyframeOutcomeUnknown,
    videoUnknown: videoOutcomeUnknown,
    referencesReady,
    videoMode,
    lastFrameCount,
    referenceCount: referenceVideoCount,
    keyframeReady: !preflightBlocks("image_keyframe"),
    videoReady: !preflightBlocks("video"),
    keyframeBlocker: modelPreflight.isError
      ? "PREFLIGHT_UNAVAILABLE"
      : (keyframePreflight?.reason ?? null),
    videoBlocker: modelPreflight.isError
      ? "PREFLIGHT_UNAVAILABLE"
      : (videoPreflight?.reason ?? null),
  });
  const focusStage: ShotExecutionStage =
    next.kind === "generate_video" ||
    next.kind === "complete" ||
    ("stage" in next && next.stage === "video")
      ? "video"
      : "image_keyframe";
  const focusPreflight = focusStage === "video" ? videoPreflight : keyframePreflight;
  const modelText = modelPreflight.isPending
    ? "正在确认…"
    : modelPreflight.isError
      ? "无法确认"
      : focusPreflight?.ready && focusPreflight.resolved_model_id
        ? `${
            focusPreflight.contract_display_name ??
            executionModelLabel(
              focusPreflight.resolved_model_id,
              Array.isArray(models.data) ? models.data : undefined,
            ).label
          }${focusPreflight.model_revision ? ` · ${focusPreflight.model_revision}` : ""}`
        : "未选择";
  const inputText =
    focusStage === "video"
      ? VIDEO_MODE_LABEL[videoMode]
      : references.length
        ? `文字描述 + ${references.length} 个参考`
        : "文字描述";
  const settingsHref = `/settings/models?returnTo=${encodeURIComponent(
    `/projects/${projectId}/scenes/${shot.scene_id}?shotId=${shot.id}`,
  )}`;

  const primary = (() => {
    switch (next.kind) {
      case "save":
        return {
          label: saving ? "正在保存…" : "保存镜头",
          testId: "shot-primary-save",
          disabled: saving || !onSave,
          run: () => onSave?.(),
        };
      case "review_candidate":
        return {
          label: "检查候选",
          testId: "shot-primary-review",
          disabled: !onReviewCandidates,
          run: () => onReviewCandidates?.(),
        };
      case "generate_keyframe":
        return {
          label: buttonLabel("image_keyframe", keyframeStatus),
          testId: "generate-keyframe",
          disabled: keyframeDisabled,
          run: () => produce.mutate("image_keyframe"),
        };
      case "generate_video":
        return {
          label: buttonLabel("video", videoStatus),
          testId: "generate-video",
          disabled: videoDisabled,
          run: () => produce.mutate("video"),
        };
      case "running":
        return {
          label: buttonLabel(next.stage, next.status),
          testId: "shot-primary-running",
          disabled: true,
          run: () => undefined,
        };
      case "unknown":
        return {
          label: "状态待同步",
          testId: "shot-primary-unknown",
          disabled: true,
          run: () => undefined,
        };
      case "complete":
        return {
          label: "已完成",
          testId: "shot-primary-complete",
          disabled: true,
          run: () => undefined,
        };
      case "blocked":
        return {
          label: next.stage === "video" ? "生成视频" : "生成画面",
          testId: next.stage === "video" ? "generate-video" : "generate-keyframe",
          disabled: true,
          run: () => undefined,
        };
    }
  })();
  const blockedReason =
    next.kind === "blocked"
      ? (NEXT_ACTION_BLOCKER_LABEL[next.reason] ??
        (next.reason === "PREFLIGHT_UNAVAILABLE"
          ? "无法确认模型，暂不生成"
          : executionModelBlockerLabel(next.reason)))
      : null;
  const blockedByModel = next.kind === "blocked" && /^(MODEL_|PROVIDER_)/.test(next.reason);
  // Secondary generation stays reachable without competing with the primary.
  const showKeyframeSecondary =
    primary.testId !== "generate-keyframe" && !keyframeDisabled && next.kind !== "save";
  const showVideoSecondary =
    primary.testId !== "generate-video" && !videoDisabled && next.kind !== "save";

  return (
    <section
      className="df-shot-generate"
      data-testid="shot-production-actions"
      data-shot-id={shot.id}
      data-next-action={next.kind}
    >
      <dl
        className="df-shot-facts"
        data-testid="shot-production-preflight"
        data-active-stage={focusStage}
      >
        <div data-testid="production-stage-indicator">
          <dt>阶段</dt>
          <dd data-testid={`stage-indicator-${focusStage}`}>
            {focusStage === "video" ? "视频生成 (图生视频)" : "画面打样 (文生图)"}
          </dd>
        </div>
        <div data-testid={`production-preflight-${focusStage}`}>
          <dt>{focusStage === "video" ? "视频模型" : "生图模型"}</dt>
          <dd title={focusPreflight?.resolved_model_id ?? undefined}>{modelText}</dd>
        </div>
        <div>
          <dt>{focusStage === "video" ? "视频输入" : "画面输入"}</dt>
          <dd>{inputText}</dd>
        </div>
        {focusStage === "video" && Boolean(shot.formal_keyframe_artifact_id) && (
          <div data-testid="production-preflight-source-frame">
            <dt>基准画面</dt>
            <dd>已绑定正式关键帧</dd>
          </div>
        )}
      </dl>

      <Button
        tone="primary"
        className="df-shot-primary"
        data-testid={primary.testId}
        disabled={primary.disabled}
        onClick={primary.run}
      >
        {primary.label}
      </Button>
      {blockedReason && (
        <p className="df-shot-hint" data-testid="shot-primary-blocked" role="status">
          {blockedReason}
          {blockedByModel && (
            <a
              href={settingsHref}
              role="button"
              onClick={(e) => {
                if (onOpenModelSettings) {
                  e.preventDefault();
                  onOpenModelSettings();
                }
              }}
            >
              去设置模型
            </a>
          )}
        </p>
      )}

      {(showKeyframeSecondary || showVideoSecondary) && (
        <div className="df-shot-secondary">
          {showKeyframeSecondary && (
            <Button
              tone="ghost"
              data-testid="secondary-generate-keyframe"
              onClick={() => produce.mutate("image_keyframe")}
            >
              {buttonLabel("image_keyframe", keyframeStatus)}
            </Button>
          )}
          {showVideoSecondary && (
            <Button
              tone="ghost"
              data-testid="secondary-generate-video"
              onClick={() => produce.mutate("video")}
            >
              {buttonLabel("video", videoStatus)}
            </Button>
          )}
        </div>
      )}

      {(keyframeQueue || videoQueue) && (
        <p className="df-shot-hint" data-testid="shot-production-queue" role="status">
          {(
            [
              keyframeQueue ? (["画面", keyframeQueue] as const) : null,
              videoQueue ? (["视频", videoQueue] as const) : null,
            ].filter(Boolean) as Array<readonly [string, NonNullable<typeof keyframeQueue>]>
          )
            .map(([label, queue]) => {
              const wait =
                queue.estimatedWaitSeconds === null
                  ? ""
                  : `，约 ${Math.max(1, Math.ceil(queue.estimatedWaitSeconds / 60))} 分钟`;
              return `${label}排队第 ${queue.position} 位${wait}`;
            })
            .join("；")}
        </p>
      )}
      {(keyframeOutcomeUnknown || videoOutcomeUnknown) && (
        <p
          className="df-shot-hint warn"
          data-testid="shot-production-outcome-unknown"
          role="status"
        >
          上次提交结果未知，已暂停这一步以免重复计费。请先核对供应商任务。
          {onOpenDetails && (
            <Button tone="ghost" onClick={onOpenDetails}>
              查看记录
            </Button>
          )}
        </p>
      )}
      {directorDelegateBlocked && (
        <p className="df-shot-hint" data-testid="shot-production-director-blocked" role="status">
          {directorCapabilities?.blocker_message}
        </p>
      )}

      {delivery && (
        <section
          className="df-shot-plan"
          data-testid="shot-execution-plan-preview"
          data-delivery={delivery}
        >
          <strong>模型适配：{referenceDeliveryLabel(delivery)}</strong>
          {displayedPlan && (
            <>
              <p data-testid="shot-execution-plan-model">执行模型：{planModel.label}</p>
              <p data-testid="shot-execution-plan-references">
                引用：完全支持 {plannedReferences.filter((row) => row.delivery === "exact").length}{" "}
                · 近似 {plannedReferences.filter((row) => row.delivery === "approximate").length} ·
                不支持 {plannedReferences.filter((row) => row.delivery === "unsupported").length}
              </p>
              {(displayedPlan.plan.capability_gaps ?? []).map((gap, index) => {
                const gapReason = capabilityGapReason(gap.reason);
                return (
                  <p key={`${gap.severity}-${index}`} className="df-shot-hint">
                    {capabilityGapSeverityLabel(gap.severity)}：{gapReason.label}
                    {(gap.controls ?? []).length ? `（${(gap.controls ?? []).join("、")}）` : ""}
                  </p>
                );
              })}
              {(displayedPlan.plan.pending_suggestions ?? []).length > 0 && (
                <div
                  className="df-shot-hint"
                  data-testid="shot-execution-plan-suggestions"
                  role="note"
                >
                  <p>以下建议本次不会使用：</p>
                  <ul>
                    {(displayedPlan.plan.pending_suggestions ?? []).map((suggestion) => (
                      <li key={suggestion.key} data-testid={`plan-suggestion-${suggestion.key}`}>
                        {suggestion.label}：{suggestion.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <details
                className="editing-diagnostics"
                data-testid="shot-execution-plan-diagnostics"
              >
                <summary>诊断详情</summary>
                <small>
                  适配 {delivery} · 模型 {planModel.raw || "无"}
                  {(displayedPlan.plan.capability_gaps ?? [])
                    .map(
                      (gap) =>
                        ` · ${gap.severity} ${gap.capability ?? ""}${gap.reason ? ` ${gap.reason}` : ""}`,
                    )
                    .join("")}
                </small>
              </details>
            </>
          )}
          {pendingApproximation && (
            <div className="df-shot-secondary">
              <Button
                tone="ghost"
                data-testid="cancel-shot-execution-approximation"
                disabled={confirmApproximation.isPending}
                onClick={() => {
                  setPendingApproximation(null);
                  setFeedback(null);
                }}
              >
                取消
              </Button>
              <Button
                tone="primary"
                data-testid="confirm-shot-execution-approximation"
                disabled={confirmApproximation.isPending}
                onClick={() => confirmApproximation.mutate(pendingApproximation)}
              >
                {confirmApproximation.isPending ? "正在重新校验…" : "确认近似适配并执行"}
              </Button>
            </div>
          )}
        </section>
      )}

      {feedback?.kind === "success" && (
        <p
          className="df-shot-hint ok"
          data-testid="shot-production-status"
          data-status={feedback.message}
          role="status"
        >
          {feedback.message === "director_queued" ? (
            <>{STAGE_NOUN[feedback.stage]}已交给导演执行。</>
          ) : (
            <>
              {STAGE_NOUN[feedback.stage]}已提交：{serverStatusLabel(feedback.message)}
              。完成后在候选中检查。
            </>
          )}
        </p>
      )}
      {feedback?.kind === "error" && (
        <p className="df-shot-hint err" data-testid="shot-production-error" role="alert">
          {/MODEL_BINDING_MISSING/.test(feedback.message) ? (
            <>
              还没有可用的{STAGE_NOUN[feedback.stage]}模型，本次没有提交。
              <a
                href={settingsHref}
                role="button"
                onClick={(e) => {
                  if (onOpenModelSettings) {
                    e.preventDefault();
                    onOpenModelSettings();
                  }
                }}
              >
                去设置模型
              </a>
            </>
          ) : (
            <>
              {STAGE_NOUN[feedback.stage]}生成失败：{feedback.message}
            </>
          )}
        </p>
      )}

      <Disclosure title="更多设置" testId="shot-generate-more">
        <Field>
          视频方式
          <Select
            aria-label="视频方式"
            value={videoMode}
            disabled={Boolean(videoStatus) || videoOutcomeUnknown || produce.isPending}
            onChange={(event) => setExplicitMode(event.target.value as ShotVideoMode)}
          >
            {(Object.keys(VIDEO_MODE_LABEL) as ShotVideoMode[]).map((mode) => (
              <option key={mode} value={mode}>
                {VIDEO_MODE_LABEL[mode]}
              </option>
            ))}
          </Select>
        </Field>
        <p className="df-shot-hint">
          {videoMode === "text_to_video"
            ? "只用镜头文字生成视频，需要支持文生视频的模型。"
            : videoMode === "last_frame"
              ? `使用一条尾帧参考（当前 ${lastFrameCount} 条）。`
              : videoMode === "first_last_frame"
                ? `正式画面作首帧，加一条尾帧参考（当前 ${lastFrameCount} 条）。`
                : videoMode === "omni_reference"
                  ? `使用镜头的参考素材（当前 ${referenceVideoCount} 条）。`
                  : "视频从正式画面开始，不会自动改用其他图片。"}
        </p>
        <div className="df-shot-secondary">
          <Button
            tone="ghost"
            data-testid="delegate-keyframe-to-director"
            onClick={() => delegate.mutate("image_keyframe")}
            disabled={keyframeDisabled || directorDelegateBlocked}
          >
            让导演执行画面
          </Button>
          <Button
            tone="ghost"
            data-testid="delegate-video-to-director"
            onClick={() => delegate.mutate("video")}
            disabled={
              busy ||
              Boolean(videoStatus) ||
              videoOutcomeUnknown ||
              directorDelegateBlocked ||
              videoMode !== "first_frame" ||
              !referencesReady ||
              dirty ||
              !shot.formal_keyframe_artifact_id ||
              preflightBlocks("video")
            }
          >
            让导演执行视频
          </Button>
        </div>
      </Disclosure>
    </section>
  );
}
