import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { artifactContentUrl } from "../../lib/api";
import {
  SHOT_PRODUCTION_TRACE_QUERY_KEY,
  setShotFormalKeyframe,
  setShotFormalVideo,
  type FormalKeyframeRead,
  type FormalVideoRead,
  type ShotLite,
} from "./api";

type ShotFormalOutputActionsProps = {
  projectId: string;
  shot: ShotLite;
  candidates: unknown[];
  onConfirmed?: (result: FormalKeyframeRead | FormalVideoRead) => void | Promise<void>;
};

type FormalStage = "image_keyframe" | "video";

type Candidate = {
  artifactId: string;
  stage: FormalStage;
  status: string;
  artifactType: string;
  nodeRunId: string | null;
  mimeType: string | null;
};

function asCandidate(value: unknown): Candidate | null {
  if (typeof value !== "object" || value === null) return null;
  const row = value as Record<string, unknown>;
  const artifactId = row.artifact_id ?? row.result_artifact_id ?? row.id;
  if (typeof artifactId !== "string" || artifactId.length === 0) return null;
  const rawStage = row.stage ?? row.node_key;
  const stage: FormalStage | null =
    rawStage === "image_keyframe" || rawStage === "keyframe"
      ? "image_keyframe"
      : rawStage === "video"
        ? "video"
        : null;
  if (stage === null) return null;
  return {
    artifactId,
    stage,
    status: typeof row.status === "string" ? row.status : "unknown",
    artifactType: typeof row.artifact_type === "string" ? row.artifact_type : "unknown",
    nodeRunId: typeof row.node_run_id === "string" ? row.node_run_id : null,
    mimeType: typeof row.mime_type === "string" ? row.mime_type : null,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Human confirmation controls for the selected shot's real Artifact
 * candidates.  Formal ids are always rendered from the Shot snapshot; this
 * component never promotes a candidate in local state.
 */
export function ShotFormalOutputActions({
  projectId,
  shot,
  candidates,
  onConfirmed,
}: ShotFormalOutputActionsProps) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<{ kind: "success" | "error"; message: string } | null>(
    null,
  );

  useEffect(() => {
    setFeedback(null);
  }, [shot.id]);

  const parsedCandidates = useMemo(
    () =>
      candidates.map(asCandidate).filter((candidate): candidate is Candidate => candidate !== null),
    [candidates],
  );

  const confirm = useMutation({
    mutationFn: async (candidate: Candidate) => {
      if (candidate.stage === "image_keyframe") {
        return setShotFormalKeyframe(projectId, shot.id, candidate.artifactId, shot.version);
      }
      return setShotFormalVideo(projectId, shot.id, candidate.artifactId, shot.version);
    },
    onMutate: () => setFeedback(null),
    onSuccess: async (result) => {
      const formalArtifactId =
        "formal_keyframe_artifact_id" in result
          ? result.formal_keyframe_artifact_id
          : result.formal_video_artifact_id;
      setFeedback({
        kind: "success",
        message: `服务端已确认 ${formalArtifactId}（Shot v${result.version}）`,
      });
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["scene-workspace", projectId, shot.scene_id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["scene-summaries", projectId],
        }),
        queryClient.invalidateQueries({
          queryKey: [SHOT_PRODUCTION_TRACE_QUERY_KEY, projectId, shot.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["shot-workbench", projectId, shot.id],
        }),
      ]);
      await onConfirmed?.(result);
    },
    onError: (error) => {
      setFeedback({ kind: "error", message: errorMessage(error) });
    },
  });

  const activeArtifactId = confirm.isPending ? confirm.variables?.artifactId : null;

  return (
    <section className="qc-shot-formal-output-actions" data-testid="shot-formal-output-actions">
      <header>
        <div>
          <span className="director-stage-kicker">正式结果确认</span>
          <strong>#{shot.shot_number} · 仅人工确认</strong>
        </div>
        <span className="qc-shot-production-version">v{shot.version}</span>
      </header>

      <dl className="qc-shot-formal-output-status" data-testid="formal-output-status">
        <dt>正式关键帧</dt>
        <dd data-testid="formal-keyframe-status">
          {shot.formal_keyframe_artifact_id ?? "尚未选择"}
        </dd>
        <dt>正式视频</dt>
        <dd data-testid="formal-video-status">{shot.formal_video_artifact_id ?? "尚未选择"}</dd>
      </dl>

      <div className="qc-shot-formal-candidates" data-testid="formal-candidate-list">
        {parsedCandidates.length === 0 ? (
          <p className="muted">当前镜头没有可确认的成功候选。</p>
        ) : (
          parsedCandidates.map((candidate) => {
            const label = candidate.stage === "image_keyframe" ? "关键帧" : "视频";
            return (
              <article
                key={`${candidate.stage}:${candidate.artifactId}`}
                data-testid={`formal-candidate-${candidate.artifactId}`}
              >
                <div>
                  <strong>{label}候选</strong>
                  <code>{candidate.artifactId}</code>
                </div>
                {candidate.artifactType === "image" ? (
                  <img
                    src={artifactContentUrl(projectId, candidate.artifactId)}
                    alt={`${label}候选 ${candidate.artifactId}`}
                    data-testid={`formal-candidate-preview-${candidate.artifactId}`}
                  />
                ) : candidate.artifactType === "video" ? (
                  <video
                    controls
                    preload="metadata"
                    src={artifactContentUrl(projectId, candidate.artifactId)}
                    data-testid={`formal-candidate-preview-${candidate.artifactId}`}
                  />
                ) : null}
                <small>
                  {candidate.status} · {candidate.artifactType}
                  {candidate.mimeType ? ` · ${candidate.mimeType}` : ""}
                  {candidate.nodeRunId ? ` · Run ${candidate.nodeRunId.slice(0, 8)}` : ""}
                </small>
                <button
                  type="button"
                  onClick={() => confirm.mutate(candidate)}
                  disabled={confirm.isPending}
                >
                  {activeArtifactId === candidate.artifactId ? "确认中…" : `设为正式${label}`}
                </button>
              </article>
            );
          })
        )}
      </div>

      {feedback?.kind === "success" && (
        <p
          className="qc-shot-formal-output-status-message"
          data-testid="formal-output-success"
          role="status"
        >
          {feedback.message}
        </p>
      )}
      {feedback?.kind === "error" && (
        <p className="qc-shot-formal-output-error" data-testid="formal-output-error" role="alert">
          确认失败：{feedback.message}
        </p>
      )}
    </section>
  );
}
