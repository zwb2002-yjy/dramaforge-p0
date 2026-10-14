import { reviewTargetHref } from "../review/reviewTarget";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Layers } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { AddArtifactToAssetDialog } from "../assets/AddArtifactToAssetDialog";
import { HumanReviewDecisionPanel } from "../review";
import { Button } from "../../components/ui";
import "./shot-inspector.css";
import {
  setShotFormalKeyframe,
  setShotFormalVideo,
  type FormalKeyframeRead,
  type FormalVideoRead,
  type ShotExecutionReference,
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
  references?: ShotExecutionReference[];
  selectedCandidate?: ShotCandidate | null;
  /** Local-only selection; the callback must not persist a candidate. */
  onPreviewCandidate?: (candidate: ShotCandidate) => void;
  /** Clear the canvas preview and refetch the SceneWorkspace after success. */
  onConfirmed?: (result: FormalKeyframeRead | FormalVideoRead) => void | Promise<void>;
  /**
   * State-driven review surface: absent until candidates exist, a single
   * "候选 · N" bar when collapsed, expanded after Generate or in review.
   */
  expanded?: boolean;
  onToggleExpanded?: () => void;
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
  references = [],
  selectedCandidate = null,
  onPreviewCandidate,
  onConfirmed,
  expanded = true,
  onToggleExpanded,
}: ShotCandidateTrayProps) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<{ kind: "success" | "error"; message: string } | null>(
    null,
  );
  const [assetCandidate, setAssetCandidate] = useState<ShotCandidate | null>(null);
  const [reviewArtifactId, setReviewArtifactId] = useState<string | null>(null);
  const [comparingCandidateId, setComparingCandidateId] = useState<string | null>(null);

  useEffect(() => {
    setFeedback(null);
    setAssetCandidate(null);
    setReviewArtifactId(null);
    setComparingCandidateId(null);
  }, [shot?.id]);

  const parsedCandidates = useMemo(
    () => parseShotCandidates(candidates).filter(isConfirmableShotCandidate),
    [candidates],
  );
  const reviewCandidate = parsedCandidates.find(
    (candidate) => candidate.artifactId === reviewArtifactId,
  );

  const characterReferences = useMemo(
    () =>
      references.filter((ref) => Boolean(ref.artifact_id) && ref.mime_type?.startsWith("image/")),
    [references],
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
    onSuccess: async (result, candidate) => {
      setFeedback({
        kind: "success",
        message:
          ("formal_keyframe_artifact_id" in result ? "已设为正式画面" : "已设为正式视频") +
          (candidate.stage === "image_keyframe" ? "，下一步生成视频。" : "，可以进入剪辑。"),
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
      setFeedback({
        kind: "error",
        message: /has not been approved by a human review decision/.test(errorMessage(error))
          ? "请先审查此候选并通过，再设为正式。"
          : errorMessage(error),
      });
    },
  });

  if (!shot) return null;
  // State-driven: the tray only exists once there is something to review, or
  // right after a generation request while the result is on its way.
  if (!parsedCandidates.length && !expanded) return null;

  const activeArtifactId = confirm.isPending ? confirm.variables?.artifactId : null;
  if (!expanded) {
    return (
      <button
        type="button"
        className="df-candidates-bar"
        data-testid="shot-candidate-tray"
        data-expanded="false"
        aria-expanded="false"
        onClick={onToggleExpanded}
      >
        <Layers size={16} aria-hidden="true" />
        <span>候选</span>
        <span className="df-num">{parsedCandidates.length}</span>
        <ChevronUp size={16} aria-hidden="true" />
      </button>
    );
  }
  return (
    <section
      className="df-candidates"
      data-testid="shot-candidate-tray"
      data-shot-id={shot.id}
      data-expanded="true"
      aria-label="候选结果"
    >
      <header className="df-candidates-header">
        <strong>
          候选 <span className="df-num muted">{parsedCandidates.length}</span>
        </strong>
        <span className="muted">预览 → 审查通过 → 设为正式</span>
        <a
          className="df-candidates-link"
          href={`/projects/${projectId}/production?view=experiments&shotId=${shot.id}`}
        >
          多版本尝试
        </a>
        {onToggleExpanded && (
          <button
            type="button"
            className="df-candidates-collapse"
            data-testid="shot-candidate-collapse"
            aria-expanded="true"
            aria-label="收起候选"
            onClick={onToggleExpanded}
          >
            <ChevronDown size={16} aria-hidden="true" />
          </button>
        )}
      </header>

      {parsedCandidates.length === 0 ? (
        <p className="df-candidates-empty" data-testid="shot-candidate-empty">
          生成完成后，候选会出现在这里。
        </p>
      ) : (
        <div className="df-candidates-list" data-testid="shot-candidate-list">
          {parsedCandidates.map((candidate) => {
            const label = shotCandidateStageLabel(candidate.stage);
            const selected =
              selectedCandidate !== null &&
              shotCandidateKey(selectedCandidate) === shotCandidateKey(candidate);
            const review = candidate.reviewAllowed
              ? { tone: "ok", text: "审查已通过" }
              : candidate.reviewDecision === "rejected"
                ? { tone: "err", text: "已拒绝" }
                : { tone: "warn", text: candidate.reviewNodeRunId ? "待人工判断" : "待审查" };
            return (
              <article
                key={shotCandidateKey(candidate)}
                className={`df-candidate${selected ? " selected" : ""}`}
                data-testid={`shot-candidate-${candidate.artifactId}`}
                data-selected={selected ? "true" : "false"}
                title={`${nodeRunStatusLabel(candidate.status)} · ${candidate.artifactId}`}
              >
                <button
                  type="button"
                  className="df-candidate-preview"
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
                  <span className="df-candidate-badge">{selected ? "预览中" : label}</span>
                </button>
                <span
                  className={`df-status ${review.tone}`}
                  data-testid={`shot-candidate-review-${candidate.artifactId}`}
                >
                  {review.text}
                </span>
                {candidate.duplicateContent && (
                  <span
                    className="df-status err"
                    data-testid={`shot-candidate-duplicate-${candidate.artifactId}`}
                  >
                    与另一候选完全相同
                  </span>
                )}
                <div className="df-candidate-actions">
                  {candidate.reviewAllowed ? (
                    <button
                      type="button"
                      className="df-btn primary"
                      data-testid={`shot-candidate-confirm-${candidate.artifactId}`}
                      onClick={() => confirm.mutate(candidate)}
                      disabled={confirm.isPending}
                    >
                      {activeArtifactId === candidate.artifactId ? "确认中…" : "设为正式"}
                    </button>
                  ) : (
                    <>
                      <Button
                        tone="primary"
                        onClick={() => {
                          setReviewArtifactId(candidate.artifactId);
                          onPreviewCandidate?.(candidate);
                        }}
                      >
                        就地审查
                      </Button>
                      <a
                        className="df-btn"
                        href={reviewTargetHref(projectId, {
                          shotId: shot.id,
                          artifactId: candidate.artifactId,
                          stage:
                            candidate.stage === "image_keyframe"
                              ? "formal_keyframe"
                              : "formal_video",
                          reviewKind:
                            candidate.stage === "image_keyframe" ? "identity" : "video_drift",
                        })}
                      >
                        审查
                      </a>
                    </>
                  )}
                  <button
                    type="button"
                    className="df-btn ghost"
                    data-testid={`shot-candidate-add-asset-${candidate.artifactId}`}
                    onClick={() => setAssetCandidate(candidate)}
                  >
                    加入资产
                  </button>
                  {characterReferences.length > 0 && (
                    <button
                      type="button"
                      className="df-btn ghost"
                      data-testid={`shot-candidate-continuity-${candidate.artifactId}`}
                      onClick={() =>
                        setComparingCandidateId((current) =>
                          current === candidate.artifactId ? null : candidate.artifactId,
                        )
                      }
                    >
                      {comparingCandidateId === candidate.artifactId ? "收起设定" : "对比设定"}
                    </button>
                  )}
                </div>
                {comparingCandidateId === candidate.artifactId && (
                  <div
                    className="df-continuity-overlay"
                    data-testid={`shot-continuity-overlay-${candidate.artifactId}`}
                  >
                    <div className="df-continuity-header">
                      <span>角色基准设定图 ({characterReferences.length})</span>
                      <button
                        type="button"
                        className="df-dialog-close"
                        style={{ width: "1.25rem", height: "1.25rem" }}
                        aria-label="关闭比对"
                        onClick={() => setComparingCandidateId(null)}
                      >
                        ×
                      </button>
                    </div>
                    <div className="df-continuity-grid">
                      {characterReferences.map((ref) => {
                        const purposeName =
                          ref.purpose === "identity"
                            ? "角色基准"
                            : ref.purpose === "clothing"
                              ? "服装设定"
                              : ref.purpose === "style"
                                ? "风格基准"
                                : ref.purpose === "pose"
                                  ? "姿势参考"
                                  : "基准设定";
                        return (
                          <div
                            key={`${candidate.artifactId}-${ref.artifact_id}`}
                            className="df-continuity-card"
                          >
                            <img
                              src={artifactContentUrl(projectId, ref.artifact_id!)}
                              alt={purposeName}
                            />
                            <span>{purposeName}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      {assetCandidate && (
        <AddArtifactToAssetDialog
          projectId={projectId}
          artifactId={assetCandidate.artifactId}
          defaultName={shot.shot_number ? `镜头 ${shot.shot_number}` : "未命名资产"}
          defaultKind={assetCandidate.artifactType === "video" ? "video" : "character"}
          artifactType={assetCandidate.artifactType}
          sourceLabel={`${shotCandidateStageLabel(assetCandidate.stage)}候选`}
          shotId={shot.id}
          onCreated={async (asset) => {
            setFeedback({ kind: "success", message: `已加入资产：${asset.name}` });
            await queryClient.invalidateQueries({ queryKey: queryKeys.asset.root(projectId) });
          }}
          onClose={() => setAssetCandidate(null)}
        />
      )}
      {reviewCandidate && (
        <section data-testid="shot-inline-review" aria-label="当前候选审查">
          <Button tone="ghost" onClick={() => setReviewArtifactId(null)}>
            返回候选
          </Button>
          <HumanReviewDecisionPanel
            projectId={projectId}
            shotId={shot.id}
            artifactId={reviewCandidate.artifactId}
            reviewKind={reviewCandidate.stage === "image_keyframe" ? "identity" : "video_drift"}
            stage={reviewCandidate.stage === "image_keyframe" ? "formal_keyframe" : "formal_video"}
            shotVersion={shot.version}
            title={reviewCandidate.stage === "image_keyframe" ? "关键帧身份审查" : "视频漂移审查"}
            showFormalAction={false}
            onChanged={async () => {
              await queryClient.invalidateQueries({
                queryKey: queryKeys.scene.workspace(projectId, shot.scene_id),
              });
            }}
          />
        </section>
      )}

      {feedback?.kind === "success" && (
        <p className="df-candidates-note ok" data-testid="shot-candidate-success" role="status">
          {feedback.message}
        </p>
      )}
      {feedback?.kind === "error" && (
        <p className="df-candidates-note err" data-testid="shot-candidate-error" role="alert">
          确认失败：{feedback.message}
        </p>
      )}
    </section>
  );
}
