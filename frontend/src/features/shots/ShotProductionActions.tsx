import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { queryKeys } from "../../lib/queryKeys";
import {
  createShotExecution,
  type ShotExecutionRead,
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
  onExecuted?: (result: ShotExecutionRead) => void | Promise<void>;
};

type ActionFeedback = {
  kind: "success" | "error";
  stage: ShotExecutionStage;
  message: string;
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
  return `shot-production:${projectId}:${shotId}:${stage}:${nonce}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
  onExecuted,
}: ShotProductionActionsProps) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<ActionFeedback | null>(null);

  useEffect(() => {
    setFeedback(null);
  }, [shot.id]);

  const produce = useMutation({
    mutationFn: async (stage: ShotExecutionStage) => {
      if (dirty) {
        // The disabled attribute is the normal UI path; keep the same guard
        // in the mutation so an imperative/event-level trigger cannot bypass
        // the unsaved-design production gate.
        throw new Error("请先保存镜头设计，再生成关键帧或视频。");
      }
      const configuredPrompt =
        stage === "image_keyframe" ? (shot.image_prompt ?? "") : (shot.video_prompt ?? "");
      const prompt = configuredPrompt.trim() || (shot.visual_description ?? "").trim();
      if (!prompt) {
        throw new Error(`请先填写${STAGE_LABEL[stage]}提示词`);
      }

      // Snapshot the selected Shot's concrete references at click time.  The
      // same immutable input object is used for both preview and execution;
      // a later picker refresh cannot make the two requests diverge.
      const executionReferences = references.map((reference) => ({ ...reference }));

      return createShotExecution(
        projectId,
        shot.id,
        {
          stage,
          prompt,
          semantic_intent: {
            intent: stage === "image_keyframe" ? "shot_keyframe" : "shot_video",
            project_id: projectId,
            scene_id: shot.scene_id,
            shot_id: shot.id,
            visual_description: shot.visual_description,
            director_state: shot.director_state,
          },
          mode_id: STAGE_MODE[stage],
          requested_model_id: null,
          requested_binding_id: null,
          accept_approximations: false,
          references: executionReferences,
          expected_shot_version: shot.version,
        },
        idempotencyKey(projectId, shot.id, stage),
      );
    },
    onMutate: (stage) => {
      setFeedback(null);
      return { stage };
    },
    onSuccess: async (result, stage) => {
      setFeedback({
        kind: "success",
        stage,
        message: `NodeRun：${result.status}`,
      });

      // SceneWorkspace carries the shot and its trace in one backend read
      // model.  Invalidate the aggregate plus the wall and trace aliases so a
      // later navigation cannot display stale production state.
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
    },
    onError: (error, stage) => {
      // Preserve the backend's real message (not a client-side success or a
      // guessed "no formal keyframe" state).  In particular, a video request
      // without a formal keyframe is rejected by the Workbench plan builder.
      setFeedback({ kind: "error", stage, message: errorMessage(error) });
    },
  });

  const activeStage = produce.isPending ? produce.variables : null;

  return (
    <section
      className="qc-shot-production-actions"
      data-testid="shot-production-actions"
      data-shot-id={shot.id}
    >
      <header>
        <div>
          <span className="director-stage-kicker">当前镜头生产</span>
          <strong>#{shot.shot_number} · 受控执行</strong>
        </div>
        <span className="qc-shot-production-version">v{shot.version}</span>
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
          disabled={produce.isPending || !referencesReady || dirty}
        >
          {activeStage === "image_keyframe" ? "关键帧入队中…" : "生成关键帧"}
        </button>
        <button
          type="button"
          data-testid="generate-video"
          onClick={() => produce.mutate("video")}
          disabled={produce.isPending || !referencesReady || dirty}
        >
          {activeStage === "video" ? "视频入队中…" : "生成视频"}
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
      {dirty && (
        <p className="qc-shot-production-hint" data-testid="shot-production-unsaved" role="status">
          请先保存镜头设计，再生成关键帧或视频。
        </p>
      )}

      {feedback?.kind === "success" && (
        <p className="qc-shot-production-status" data-testid="shot-production-status" role="status">
          {STAGE_LABEL[feedback.stage]}已提交：{feedback.message}
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
