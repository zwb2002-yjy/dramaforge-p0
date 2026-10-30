import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, Disclosure, ExternalLink, Field, Select } from "../../components/ui";

import { queryKeys } from "../../lib/queryKeys";
import { ApiError } from "../../lib/api";
import { getExecutionModelPreflight, listModels } from "../model-controls/api";
import { ShotPreflightDrawer } from "./ShotPreflightDrawer";
import { receiptCopy } from "./receiptCopy";
import {
  capabilityGapReason,
  capabilityGapSeverityLabel,
  executionModelLabel,
  referenceDeliveryLabel,
} from "../../lib/executionPlanLabels";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import { executionModelBlockerLabel, modelPreflightCopy } from "../../lib/modelResolutionLabels";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import {
  activeStageStatus,
  stageOutcomeUnknown,
  stageQueueEstimate,
} from "../production/sceneRunState";
import { fetchDirectorCapabilities } from "../director/api";
import { fetchShotReferences } from "../assets/api";
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
  promptReferencesReady?: { image_keyframe: boolean; video: boolean };
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
  configuredVideoMode?: ShotVideoMode;
  onVideoModeChange?: (mode: ShotVideoMode) => void;
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
    duration_seconds: preview.plan.duration_seconds,
    effective_options: preview.plan.effective_options,
    prompt_override: preview.plan.prompt_override,
    exact_controls: preview.plan.exact_controls,
    approximate_controls: preview.plan.approximate_controls,
    unsupported_controls: preview.plan.unsupported_controls,
    semantic_request_preview: preview.plan.semantic_request_preview,
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
  promptReferencesReady = { image_keyframe: true, video: true },
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
  configuredVideoMode,
  onVideoModeChange,
}: ShotProductionActionsProps) {
  const workspaceId = getSelectedWorkspaceId();
  const queryClient = useQueryClient();
  const savedBindings = useQuery({
    queryKey: queryKeys.asset.shotReferences(projectId, shot.id),
    queryFn: () => fetchShotReferences(projectId, shot.id),
  });
  const delegationDecisionIds = useRef(
    new Map<string, { decisionId: string; authorizationExpiresAt: string }>(),
  );
  const preflightSequence = useRef(0);
  const explicitCreateId = useRef(globalThis.crypto.randomUUID());
  const forStage = (stage: "image" | "video") =>
    references.filter((reference) => {
      const row = (Array.isArray(savedBindings.data) ? savedBindings.data : []).find(
        (binding) => binding.id === reference.binding_id,
      );
      return !row || row.stage === "both" || row.stage === stage;
    });
  const imageReferences = forStage("image");
  const videoReferences = forStage("video");
  const lastFrameCount = videoReferences.filter(
    (reference) => reference.purpose === "last_frame",
  ).length;
  // The mode follows saved facts until the creator picks one explicitly.
  const [explicitMode, setExplicitMode] = useState<ShotVideoMode | null>(null);
  const videoMode =
    configuredVideoMode ??
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
  const referenceVideoCount = videoReferences.filter((reference) =>
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
    queryKey: queryKeys.model.catalog(workspaceId),
    queryFn: ({ signal }) => listModels(undefined, workspaceId, signal),
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
  const [receiptCheck, setReceiptCheck] = useState(0);
  const receiptScope = `${workspaceId}:${projectId}:${shot.id}`;
  const [receiptState, setReceiptState] = useState<{
    scope: string;
    stages: Partial<Record<ShotExecutionStage, "checking" | "unknown" | "failed">>;
  }>({ scope: receiptScope, stages: {} });
  const receiptIssues =
    receiptState.scope === receiptScope ? Object.values(receiptState.stages) : [];
  const [displayedPlan, setDisplayedPlan] = useState<ShotExecutionPlanRead | null>(null);
  const [pendingApproximation, setPendingApproximation] = useState<PreparedShotExecution | null>(
    null,
  );
  const [planFailure, setPlanFailure] = useState<"unsupported" | null>(null);
  const [preflightDrawerStage, setPreflightDrawerStage] = useState<ShotExecutionStage | null>(null);
  const [approximationsAccepted, setApproximationsAccepted] = useState(false);

  useEffect(() => {
    preflightSequence.current += 1;
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
    setReceiptState({ scope: receiptScope, stages: {} });
    const stages: ShotExecutionStage[] = ["image_keyframe", "video"];
    const updateReceipt = (
      stage: ShotExecutionStage,
      state?: "checking" | "unknown" | "failed",
    ) => {
      if (cancelled) return;
      setReceiptState((previous) => {
        const next = previous.scope === receiptScope ? { ...previous.stages } : {};
        if (state) next[stage] = state;
        else delete next[stage];
        return { scope: receiptScope, stages: next };
      });
    };
    for (const stage of stages) {
      const scope = productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, stage);
      const operation = readProductionOperation(scope);
      if (!operation) continue;
      updateReceipt(stage, "checking");
      void fetchShotExecutionReceipt(projectId, shot.id, stage, operation.operationKey)
        .then((receipt) => {
          if (cancelled) return;
          if (!receipt) {
            updateReceipt(stage, "unknown");
            return;
          }
          updateReceipt(stage);
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
          updateReceipt(stage, "failed");
        });
    }
    return () => {
      cancelled = true;
    };
  }, [projectId, shot.id, workspaceId, receiptScope, receiptCheck]);

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
        ? imageReferences
        : videoMode === "text_to_video"
          ? []
          : videoMode === "last_frame" || videoMode === "first_last_frame"
            ? videoReferences.filter((reference) => reference.purpose === "last_frame")
            : videoMode === "omni_reference"
              ? videoReferences.filter(
                  (reference) => !["first_frame", "last_frame"].includes(reference.purpose),
                )
              : videoReferences
      )
        .filter((reference) => {
          const row = (Array.isArray(savedBindings.data) ? savedBindings.data : []).find(
            (binding) => binding.id === reference.binding_id,
          );
          return (
            !row || row.stage === "both" || row.stage === (stage === "video" ? "video" : "image")
          );
        })
        .map((reference) => ({ ...reference })),
      expected_shot_version: shot.version,
    };
  }

  const inspectPlan = useMutation({
    retry: false,
    mutationFn: (
      target: ShotExecutionStage | { stage: ShotExecutionStage; acceptApproximations?: boolean },
    ) => {
      const stage = typeof target === "string" ? target : target.stage;
      const acceptApproximations =
        typeof target === "string" ? false : Boolean(target.acceptApproximations);
      if (dirty || !referencesReady || !promptReferencesReady[stage])
        throw new Error("请先保存镜头并处理未解析的素材引用。");
      const input: ShotExecutionInput = {
        ...executionInput(stage),
        accept_approximations: acceptApproximations,
      };
      return previewShotExecution(projectId, shot.id, input);
    },
    onMutate: () => ++preflightSequence.current,
    onSuccess: (plan, _target, sequence) => {
      if (
        sequence !== preflightSequence.current ||
        (plan.plan.shot_id && plan.plan.shot_id !== shot.id) ||
        (plan.plan.expected_shot_version != null &&
          plan.plan.expected_shot_version !== shot.version)
      ) {
        return;
      }
      setDisplayedPlan(plan);
    },
  });
  // Compare saved input values, so equivalent query refreshes and parent
  // renders keep the confirmation open while changed execution facts expire it.
  const referenceKey = JSON.stringify(references);
  const bindingScopeKey = (Array.isArray(savedBindings.data) ? savedBindings.data : [])
    .map((binding) => `${binding.id}:${binding.stage}`)
    .sort()
    .join("|");
  const modelResolutionKey = Array.isArray(modelPreflight.data?.stages)
    ? JSON.stringify(
        modelPreflight.data.stages
          .map((stage) => ({
            stage: stage.stage,
            ready: stage.ready,
            source: stage.source,
            requested_model_id: stage.requested_model_id,
            resolved_model_id: stage.resolved_model_id,
            provider_model_binding_id: stage.provider_model_binding_id,
            model_revision: stage.model_revision,
            reason: stage.reason,
          }))
          .sort((left, right) => left.stage.localeCompare(right.stage)),
      )
    : null;
  const previousModelResolutionKey = useRef<string | null>(null);
  const invalidatePreflight = useCallback(() => {
    preflightSequence.current += 1;
    setDisplayedPlan(null);
    setPendingApproximation(null);
    setApproximationsAccepted(false);
  }, []);
  useEffect(invalidatePreflight, [
    invalidatePreflight,
    shot.version,
    dirty,
    referenceKey,
    videoMode,
    bindingScopeKey,
  ]);
  useEffect(() => {
    if (modelResolutionKey === null) return;
    const previous = previousModelResolutionKey.current;
    previousModelResolutionKey.current = modelResolutionKey;
    // The first read establishes the model baseline. It must not discard an
    // inspection already in flight while that initial read was loading.
    if (previous !== null && previous !== modelResolutionKey) invalidatePreflight();
  }, [invalidatePreflight, modelResolutionKey]);

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

  // Creating media is ALWAYS a two-action flow: preview the exact Compiler
  // projection, then require a separate explicit confirmation in the drawer.
  // Never persist an operation key or issue /executions from this mutation.
  const produce = useMutation<PrepareOutcome, unknown, ShotExecutionStage>({
    mutationFn: async (stage) => {
      if (dirty || !referencesReady || !promptReferencesReady[stage]) {
        throw new Error("请先保存镜头设计并处理未解析的素材引用，再生成。");
      }
      const input = executionInput(stage);
      const preview = await previewShotExecution(projectId, shot.id, input);
      return {
        stage,
        prepared: {
          input,
          preview,
          idempotencyKey: shotExecutionIdempotencyKey(shot.id, preview.plan_fingerprint),
        },
      };
    },
    onMutate: () => {
      setFeedback(null);
      explicitCreateId.current = globalThis.crypto.randomUUID();
      return ++preflightSequence.current;
    },
    onSuccess: ({ stage, prepared }, _stage, sequence) => {
      if (sequence !== preflightSequence.current) return;
      setDisplayedPlan(prepared.preview);
      setPlanFailure(null);
      setApproximationsAccepted(false);
      setPreflightDrawerStage(stage);
      if (planDelivery(prepared.preview) === "approximate") {
        setPendingApproximation(prepared);
        setFeedback({ kind: "plan", stage, message: "approximate" });
      } else {
        setPendingApproximation(null);
      }
    },
    onError: (error, stage) => {
      setDisplayedPlan(null);
      setPendingApproximation(null);
      const message = errorMessage(error);
      setPlanFailure(/unsupported|capability gap|不支持/i.test(message) ? "unsupported" : null);
      setFeedback({ kind: "error", stage, message });
    },
  });

  // The secondary approximation action only requests a new accepted plan.
  // The user still reviews its redacted Provider wire in the shared drawer
  // before a separate explicit /executions submission.
  const confirmApproximation = useMutation({
    mutationFn: async (prepared: PreparedShotExecution) => {
      const input: ShotExecutionInput = {
        ...prepared.input,
        accept_approximations: true,
      };
      const acceptedPreview = await previewShotExecution(projectId, shot.id, input);
      if (stablePlanIdentity(acceptedPreview) !== stablePlanIdentity(prepared.preview)) {
        throw new Error("模型、引用或创作意图在确认期间已变化，请重新生成并确认计划。");
      }
      return { stage: input.stage, preview: acceptedPreview };
    },
    onSuccess: ({ stage, preview }) => {
      setDisplayedPlan(preview);
      setPendingApproximation(null);
      setPlanFailure(null);
      setApproximationsAccepted(true);
      setPreflightDrawerStage(stage);
    },
    onError: (error) => {
      const stage = pendingApproximation?.input.stage ?? "image_keyframe";
      setFeedback({ kind: "error", stage, message: errorMessage(error) });
    },
  });

  const executeConfirmedPlan = useMutation({
    mutationFn: async ({
      stage,
      plan,
      acceptApproximations,
    }: {
      stage: ShotExecutionStage;
      plan: ShotExecutionPlanRead;
      acceptApproximations: boolean;
    }) => {
      if (dirty) {
        throw new Error("请先保存镜头设计，再生成关键帧或视频。");
      }
      const input: ShotExecutionInput = {
        ...executionInput(stage),
        accept_approximations: acceptApproximations,
      };
      let effectivePlan = plan;
      const hasWarningGaps = (plan.plan.capability_gaps ?? []).some(
        (g) => g.severity === "warning",
      );
      const unacceptedInPlan = (plan.plan.accepted_approximations ?? []).length === 0;
      if (acceptApproximations && (hasWarningGaps || unacceptedInPlan)) {
        effectivePlan = await previewShotExecution(projectId, shot.id, input);
        if (
          stablePlanIdentity(effectivePlan) !== stablePlanIdentity(plan) ||
          effectivePlan.compiler_contract_preview?.wire_fingerprint !==
            plan.compiler_contract_preview?.wire_fingerprint
        ) {
          throw new Error("执行参数或编译请求在确认期间已变化，请重新预检。");
        }
      }
      const prepared: PreparedShotExecution = {
        input,
        preview: effectivePlan,
        idempotencyKey: shotExecutionIdempotencyKey(
          shot.id,
          effectivePlan.plan_fingerprint,
          explicitCreateId.current,
        ),
      };
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
    onMutate: () => setFeedback(null),
    onSuccess: async ({ stage, prepared, execution }) => {
      setDisplayedPlan(prepared.preview);
      setPlanFailure(null);
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
    onError: (error, { stage }) => {
      const message = errorMessage(error);
      if (submissionProvablyEnded(error)) {
        clearProductionOperation(
          productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, stage),
        );
      }
      setFeedback({ kind: "error", stage, message });
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
      const decisionKey = [
        shot.id,
        stage,
        preview.plan_fingerprint,
        preview.compiler_contract_preview?.wire_fingerprint ?? "unverified",
      ].join(":");
      let frozenDecision = delegationDecisionIds.current.get(decisionKey);
      if (!frozenDecision) {
        frozenDecision = {
          decisionId: globalThis.crypto.randomUUID(),
          authorizationExpiresAt: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
        };
        delegationDecisionIds.current.set(decisionKey, frozenDecision);
      }
      const turn = await delegateShotExecutionToDirector(projectId, shot.id, {
        input,
        preview,
        ...frozenDecision,
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
    : executeConfirmedPlan.isPending
      ? executeConfirmedPlan.variables.stage
      : delegate.isPending
        ? delegate.variables
        : confirmApproximation.isPending
          ? (pendingApproximation?.input.stage ?? null)
          : null;
  const keyframeStatus = activeStageStatus(trace, "image_keyframe");
  const videoStatus = activeStageStatus(trace, "video");
  // A lost browser response is not proof that the paid request was rejected.
  // Until the durable command is reconciled with server trace/receipt, block
  // another paid create even if the caller supplied an empty/stale trace.
  const keyframeOutcomeUnknown =
    stageOutcomeUnknown(trace, "image_keyframe") ||
    Boolean(
      readProductionOperation(
        productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, "image_keyframe"),
      ) && !keyframeStatus,
    );
  const videoOutcomeUnknown =
    stageOutcomeUnknown(trace, "video") ||
    Boolean(
      readProductionOperation(
        productionOperationScope(getSelectedWorkspaceId(), projectId, shot.id, "video"),
      ) && !videoStatus,
    );
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
    inspectPlan.isPending ||
    produce.isPending ||
    executeConfirmedPlan.isPending ||
    delegate.isPending ||
    confirmApproximation.isPending ||
    Boolean(pendingApproximation);
  const keyframeDisabled =
    busy ||
    Boolean(keyframeStatus) ||
    keyframeOutcomeUnknown ||
    !referencesReady ||
    !promptReferencesReady.image_keyframe ||
    dirty ||
    preflightBlocks("image_keyframe");
  const videoDisabled =
    busy ||
    Boolean(videoStatus) ||
    videoOutcomeUnknown ||
    (videoMode !== "text_to_video" && !referencesReady) ||
    !promptReferencesReady.video ||
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
    referencesReady:
      referencesReady &&
      promptReferencesReady[
        shot.formal_keyframe_artifact_id ||
        videoMode === "text_to_video" ||
        videoMode === "last_frame"
          ? "video"
          : "image_keyframe"
      ],
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
  const modelSettingsAction = (
    <ExternalLink
      type="link"
      href={settingsHref}
      role="button"
      onClick={(event) => {
        if (onOpenModelSettings) {
          event.preventDefault();
          onOpenModelSettings();
        }
      }}
    >
      {modelPreflightCopy.configure}
    </ExternalLink>
  );
  const inspectionModelReason =
    inspectPlan.error instanceof ApiError &&
    typeof inspectPlan.error.details.resolution_status === "string" &&
    typeof inspectPlan.error.details.code === "string"
      ? executionModelBlockerLabel(inspectPlan.error.details.code)
      : null;

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
      {receiptIssues.length > 0 && (
        <div
          role={receiptIssues.includes("failed") ? "alert" : "status"}
          data-testid="receipt-reconciliation"
        >
          <p>
            {receiptIssues.includes("checking")
              ? receiptCopy.checking
              : receiptIssues.includes("failed")
                ? receiptCopy.failed
                : receiptCopy.unknown}
          </p>
          <Button
            disabled={receiptIssues.includes("checking")}
            onClick={() => setReceiptCheck((value) => value + 1)}
          >
            {receiptCopy.retry}
          </Button>
        </div>
      )}
      <dl
        className="df-shot-facts"
        data-testid="shot-production-preflight"
        data-active-stage={focusStage}
      >
        <div data-testid="production-stage-indicator">
          <dt>阶段</dt>
          <dd data-testid={`stage-indicator-${focusStage}`}>
            {focusStage === "video" ? `视频生成 (${VIDEO_MODE_LABEL[videoMode]})` : "画面打样"}
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
        {focusStage === "video" &&
          (videoMode === "first_frame" || videoMode === "first_last_frame") &&
          Boolean(shot.formal_keyframe_artifact_id) && (
            <div data-testid="production-preflight-source-frame">
              <dt>基准画面</dt>
              <dd>已绑定正式关键帧</dd>
            </div>
          )}
      </dl>

      <Button
        tone="primary"
        block
        size="large"
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
          {blockedByModel && modelSettingsAction}
        </p>
      )}
      <Button
        tone="ghost"
        data-testid="inspect-shot-plan"
        disabled={busy || dirty || !referencesReady || !promptReferencesReady[focusStage]}
        onClick={() => {
          explicitCreateId.current = globalThis.crypto.randomUUID();
          setPreflightDrawerStage(focusStage);
          setApproximationsAccepted(false);
          inspectPlan.mutate({ stage: focusStage, acceptApproximations: false });
        }}
      >
        {inspectPlan.isPending ? "正在核对输入…" : "查看生成预检"}
      </Button>
      {inspectPlan.isError && (
        <div className="df-shot-hint err" data-testid="shot-plan-error">
          <p role={preflightDrawerStage === null ? "alert" : "status"}>
            {modelPreflightCopy.failed}：{inspectionModelReason ?? errorMessage(inspectPlan.error)}
          </p>
          {inspectionModelReason && (
            <>
              {modelSettingsAction}
              <Disclosure compact title={modelPreflightCopy.diagnostics}>
                <small>{errorMessage(inspectPlan.error)}</small>
              </Disclosure>
            </>
          )}
        </div>
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
              <p data-testid="shot-execution-plan-prompt">
                最终提示词：{displayedPlan.plan.prompt}
              </p>
              {Array.isArray(displayedPlan.plan.semantic_intent?.prompt_reference_map) && (
                <ul data-testid="shot-prompt-reference-map">
                  {displayedPlan.plan.semantic_intent.prompt_reference_map.map((row, index) => {
                    if (
                      !row ||
                      typeof row !== "object" ||
                      Array.isArray(row) ||
                      typeof row.label !== "string" ||
                      typeof row.notation !== "string"
                    )
                      return null;
                    return (
                      <li key={index}>
                        {row.label} → {row.notation}
                      </li>
                    );
                  })}
                </ul>
              )}
              {delivery === "exact" ? (
                <Disclosure
                  compact
                  className="df-shot-plan-details"
                  data-testid="shot-exact-plan-details"
                  title={<>查看本次模型与参考</>}
                >
                  <p data-testid="shot-execution-plan-model">执行模型：{planModel.label}</p>
                  <p data-testid="shot-execution-plan-references">
                    引用：完全支持{" "}
                    {plannedReferences.filter((row) => row.delivery === "exact").length} · 近似{" "}
                    {plannedReferences.filter((row) => row.delivery === "approximate").length} ·
                    不支持{" "}
                    {plannedReferences.filter((row) => row.delivery === "unsupported").length}
                  </p>
                </Disclosure>
              ) : (
                <>
                  <p data-testid="shot-execution-plan-model">执行模型：{planModel.label}</p>
                  <p data-testid="shot-execution-plan-references">
                    引用：完全支持{" "}
                    {plannedReferences.filter((row) => row.delivery === "exact").length} · 近似{" "}
                    {plannedReferences.filter((row) => row.delivery === "approximate").length} ·
                    不支持{" "}
                    {plannedReferences.filter((row) => row.delivery === "unsupported").length}
                  </p>
                </>
              )}
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
              <Disclosure
                compact
                className="editing-diagnostics"
                data-testid="shot-execution-plan-diagnostics"
                title={<>诊断详情</>}
              >
                <small>
                  适配 {delivery} · 模型 {planModel.raw || "无"}
                  {(displayedPlan.plan.capability_gaps ?? [])
                    .map(
                      (gap) =>
                        ` · ${gap.severity} ${gap.capability ?? ""}${gap.reason ? ` ${gap.reason}` : ""}`,
                    )
                    .join("")}
                </small>
              </Disclosure>
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
                {confirmApproximation.isPending ? "正在重新校验…" : "查看近似适配请求"}
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
              {modelSettingsAction}
            </>
          ) : (
            <>
              {STAGE_NOUN[feedback.stage]}生成失败：{feedback.message}
            </>
          )}
        </p>
      )}

      <Disclosure compact title="更多设置" testId="shot-generate-more">
        <Field>
          视频方式
          <Select
            aria-label="视频方式"
            value={videoMode}
            disabled={Boolean(videoStatus) || videoOutcomeUnknown || produce.isPending}
            onChange={(event) => {
              const mode = event as ShotVideoMode;
              if (onVideoModeChange) onVideoModeChange(mode);
              else setExplicitMode(mode);
            }}
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

      <ShotPreflightDrawer
        open={preflightDrawerStage !== null}
        onClose={() => setPreflightDrawerStage(null)}
        stage={preflightDrawerStage ?? focusStage}
        rawPrompt={
          (preflightDrawerStage ?? focusStage) === "video"
            ? shot.video_prompt || shot.visual_description || ""
            : shot.image_prompt || shot.visual_description || ""
        }
        plan={displayedPlan}
        isLoading={inspectPlan.isPending}
        error={inspectPlan.error instanceof Error ? inspectPlan.error : null}
        errorSummary={inspectionModelReason}
        recoveryAction={
          inspectionModelReason ? (
            <Button
              onClick={() => {
                setPreflightDrawerStage(null);
                if (onOpenModelSettings) onOpenModelSettings();
                else window.location.assign(settingsHref);
              }}
            >
              去设置模型
            </Button>
          ) : undefined
        }
        dirty={dirty}
        onSaveAndRecompute={async () => {
          await onSave?.();
          if (preflightDrawerStage) {
            inspectPlan.mutate({
              stage: preflightDrawerStage,
              acceptApproximations: approximationsAccepted,
            });
          }
        }}
        onConfirmGenerate={() => {
          if (preflightDrawerStage) {
            if (displayedPlan) {
              executeConfirmedPlan.mutate({
                stage: preflightDrawerStage,
                plan: displayedPlan,
                acceptApproximations: approximationsAccepted,
              });
            }
            setPreflightDrawerStage(null);
          }
        }}
        isGenerating={produce.isPending || executeConfirmedPlan.isPending}
        approximationsAccepted={approximationsAccepted}
        onAcceptApproximationsChange={(accepted) => {
          setApproximationsAccepted(accepted);
          if (preflightDrawerStage) {
            inspectPlan.mutate({
              stage: preflightDrawerStage,
              acceptApproximations: accepted,
            });
          }
        }}
      />
    </section>
  );
}
