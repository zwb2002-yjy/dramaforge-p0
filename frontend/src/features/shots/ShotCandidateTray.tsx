import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  setShotFormalKeyframe,
  setShotFormalVideo,
  type FormalKeyframeRead,
  type FormalVideoRead,
  type ShotLite,
} from "./api";
import {
  isConfirmableShotCandidate,
  parseShotCandidates,
  shotCandidateKey,
  shotCandidateStageLabel,
  type ShotCandidate,
} from "./shotCandidates";

type ShotCandidateTrayProps = {
  projectId: string;
  shot: ShotLite | null;
  candidates?: unknown[];
  selectedCandidate?: ShotCandidate | null;
  /** Local-only selection; the callback must not persist a candidate. */
  onPreviewCandidate?: (candidate: ShotCandidate) => void;
  /** Clear the canvas preview and refetch the SceneWorkspace after success. */
  onConfirmed?: (result: FormalKeyframeRead | FormalVideoRead) => void | Promise<void>;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Candidate comparison and formal-selection surface for the selected Shot.
 *
 * Candidate previews are deliberately separate from confirmation.  Clicking
 * a thumbnail only tells the SceneWorkspace which Artifact to show on the
 * canvas.  The explicit confirmation button is the only mutation and sends
 * the exact Shot version captured by this read model to the existing formal
 * selection endpoint.
 */
export function ShotCandidateTray({
  projectId,
  shot,
  candidates = [],
  selectedCandidate = null,
  onPreviewCandidate,
  onConfirmed,
}: ShotCandidateTrayProps) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<{ kind: "success" | "error"; message: string } | null>(
    null,
  );

  useEffect(() => {
    setFeedback(null);
  }, [shot?.id]);

  const parsedCandidates = useMemo(
    () => parseShotCandidates(candidates).filter(isConfirmableShotCandidate).slice(0, 4),
    [candidates],
  );

  const confirm = useMutation({
    mutationFn: async (candidate: ShotCandidate) => {
      if (!shot) throw new Error("请先选择镜头");
      if (!isConfirmableShotCandidate(candidate)) {
        throw new Error("仅可确认已完成且可用的媒体候选。");
      }
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
        message: `已确认 ${formalArtifactId}（Shot v${result.version}）`,
      });
      // Keep the existing cache aliases coherent.  No browser-side Shot or
      // formal id is manufactured; the follow-up workspace read is the truth.
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.scene.workspace(projectId, shot?.scene_id),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.scene.summaries(projectId),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.shot.productionTrace(projectId, shot?.id),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.shot.workbench(projectId, shot?.id),
        }),
      ]);
      await onConfirmed?.(result);
    },
    onError: (error) => {
      // Stale-version conflicts remain visible and fail closed.  We do not
      // mark a candidate formal or alter the local canvas on error.
      setFeedback({ kind: "error", message: errorMessage(error) });
    },
  });

  if (!shot) {
    return (
      <section className="qc-shot-candidate-tray" data-testid="shot-candidate-tray">
        <p className="muted">选择一个镜头比较候选结果。</p>
      </section>
    );
  }

  const activeArtifactId = confirm.isPending ? confirm.variables?.artifactId : null;
  return (
    <section
      className="qc-shot-candidate-tray"
      data-testid="shot-candidate-tray"
      data-shot-id={shot.id}
      aria-label="候选结果"
    >
      <header className="qc-shot-candidate-tray-header">
        <div>
          <span className="director-stage-kicker">候选比较</span>
          <strong>候选结果 · #{shot.shot_number}</strong>
        </div>
        <span className="qc-shot-candidate-count">
          {parsedCandidates.length ? `${parsedCandidates.length} 个可确认候选` : "暂无可确认候选"}
        </span>
      </header>

      {parsedCandidates.length === 0 ? (
        <p className="muted" data-testid="shot-candidate-empty">
          生产链完成后，候选媒体会出现在这里；实验分支不会混入正式候选。
        </p>
      ) : (
        <div className="qc-shot-candidate-list" data-testid="shot-candidate-list">
          {parsedCandidates.map((candidate) => {
            const label = shotCandidateStageLabel(candidate.stage);
            const selected =
              selectedCandidate !== null &&
              shotCandidateKey(selectedCandidate) === shotCandidateKey(candidate);
            return (
              <article
                key={shotCandidateKey(candidate)}
                className={`qc-shot-candidate-card${selected ? " selected" : ""}`}
                data-testid={`shot-candidate-${candidate.artifactId}`}
                data-selected={selected ? "true" : "false"}
              >
                <button
                  type="button"
                  className="qc-shot-candidate-preview"
                  data-testid={`shot-candidate-select-${candidate.artifactId}`}
                  aria-label={`预览${label}候选 ${candidate.artifactId}`}
                  aria-pressed={selected}
                  onClick={() => onPreviewCandidate?.(candidate)}
                >
                  {candidate.artifactType === "video" ? (
                    <video
                      muted
                      preload="metadata"
                      src={artifactContentUrl(projectId, candidate.artifactId)}
                      aria-label={`${label}候选 ${candidate.artifactId}`}
                    />
                  ) : (
                    <img
                      src={artifactContentUrl(projectId, candidate.artifactId)}
                      alt={`${label}候选 ${candidate.artifactId}`}
                    />
                  )}
                  <span className="qc-shot-candidate-badge">{selected ? "正在预览" : label}</span>
                </button>
                <div className="qc-shot-candidate-meta">
                  <span>{candidate.status}</span>
                  {candidate.nodeRunId && <small>Run {candidate.nodeRunId.slice(0, 8)}</small>}
                  <code>{candidate.artifactId}</code>
                </div>
                <button
                  type="button"
                  className="qc-shot-candidate-confirm"
                  data-testid={`shot-candidate-confirm-${candidate.artifactId}`}
                  onClick={() => confirm.mutate(candidate)}
                  disabled={confirm.isPending}
                >
                  {activeArtifactId === candidate.artifactId ? "确认中…" : `设为正式${label}`}
                </button>
              </article>
            );
          })}
        </div>
      )}

      {feedback?.kind === "success" && (
        <p className="qc-shot-candidate-success" data-testid="shot-candidate-success" role="status">
          {feedback.message}
        </p>
      )}
      {feedback?.kind === "error" && (
        <p className="qc-shot-candidate-error" data-testid="shot-candidate-error" role="alert">
          确认失败：{feedback.message}
        </p>
      )}
    </section>
  );
}
