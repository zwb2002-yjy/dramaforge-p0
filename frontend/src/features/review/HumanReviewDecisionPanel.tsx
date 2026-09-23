import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { queryKeys } from "../../lib/queryKeys";
import { reviewBlockerLabel, reviewMachineStatusLabel } from "./reviewLabels";
import {
  createReviewDecision,
  createReviewEvidence,
  fetchReviewSummary,
  type ReviewDecisionWrite,
  type ReviewStage,
  type ReviewSummaryRead,
} from "./reviewDecisionApi";
import { setShotFormalKeyframe, setShotFormalVideo } from "../shots/api";

type ReviewDecisionPanelProps = {
  projectId: string;
  shotId: string;
  /** Immutable Artifact under judgement; never re-resolved from "current formal". */
  artifactId: string;
  reviewKind: ReviewDecisionWrite["review_kind"];
  stage: ReviewStage;
  /** Server Shot version this page is looking at (optimistic lock). */
  shotVersion: number;
  title: string;
};

/**
 * One human judgement area: automatic evidence, the current decision, and the
 * two explicit actions. Approving here never sets Formal by itself.
 */
export function HumanReviewDecisionPanel(props: ReviewDecisionPanelProps) {
  // Drafts, idempotency keys and pending mutation feedback belong to one target.
  // Remount the session so a late response for A cannot update B's judgement UI.
  const identity = JSON.stringify([
    props.projectId,
    props.shotId,
    props.artifactId,
    props.reviewKind,
    props.stage,
  ]);
  return <ReviewDecisionSession key={identity} {...props} />;
}
function ReviewDecisionSession({
  projectId,
  shotId,
  artifactId,
  reviewKind,
  stage,
  shotVersion,
  title,
}: ReviewDecisionPanelProps) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const requestKey = useRef(`review:${globalThis.crypto.randomUUID()}`);

  const summary = useQuery({
    queryKey: queryKeys.review.summary(projectId, shotId, artifactId, reviewKind, stage),
    queryFn: () => fetchReviewSummary(projectId, shotId, artifactId, reviewKind, stage),
    enabled: Boolean(projectId) && Boolean(shotId) && Boolean(artifactId),
  });

  const decide = useMutation({
    mutationFn: (decision: "approved" | "rejected" | "demo_confirmed") =>
      createReviewDecision(
        projectId,
        shotId,
        {
          artifact_id: artifactId,
          review_node_run_id: summary.data?.review_node_run_id ?? "",
          review_kind: reviewKind,
          decision,
          reason: reason.trim(),
          expected_shot_version: summary.data?.shot_version ?? shotVersion,
        },
        requestKey.current,
      ),
    onSuccess: async (saved) => {
      // A new decision is a new operation: the next submit must use a new key.
      requestKey.current = `review:${globalThis.crypto.randomUUID()}`;
      const nextStep =
        saved.decision === "approved"
          ? "下一步：可设为镜头正式素材。"
          : saved.decision === "rejected"
            ? "下一步：调整提示词后重新生成候选。"
            : "下一步：如需正式放行，请完成视觉质检并人工通过。";
      setFeedback(
        saved.decision === "approved"
          ? `已记录人工通过：镜头 ${shotId}，素材 ${artifactId}。${nextStep}`
          : saved.decision === "rejected"
            ? `已记录人工拒绝：镜头 ${shotId}，素材 ${artifactId}。${nextStep}`
            : `已记录演示流程确认：镜头 ${shotId}，素材 ${artifactId}；该状态不会放行正式素材。${nextStep}`,
      );
      await queryClient.invalidateQueries({
        queryKey: queryKeys.review.summary(projectId, shotId, artifactId, reviewKind, stage),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.shot.reviewWorkbench(projectId, shotId),
      });
    },
    onError: (error: unknown) => {
      setFeedback(`记录决定失败：${error instanceof Error ? error.message : String(error)}`);
    },
  });

  const approveAndFormal = useMutation({
    mutationFn: async () => {
      let decision = summary.data?.decision ?? null;
      if (decision !== "approved") {
        const saved = await createReviewDecision(
          projectId,
          shotId,
          {
            artifact_id: artifactId,
            review_node_run_id: summary.data?.review_node_run_id ?? "",
            review_kind: reviewKind,
            decision: "approved",
            reason: reason.trim(),
            expected_shot_version: summary.data?.shot_version ?? shotVersion,
          },
          requestKey.current,
        );
        decision = saved.decision;
        requestKey.current = `review:${globalThis.crypto.randomUUID()}`;
      }
      if (decision !== "approved") throw new Error("人工判断未被记录为通过");
      const formal =
        stage === "formal_keyframe"
          ? await setShotFormalKeyframe(
              projectId,
              shotId,
              artifactId,
              summary.data?.shot_version ?? shotVersion,
            )
          : stage === "formal_video"
            ? await setShotFormalVideo(
                projectId,
                shotId,
                artifactId,
                summary.data?.shot_version ?? shotVersion,
              )
            : null;
      if (!formal) throw new Error("交付审查不支持设为镜头正式素材");
      return formal;
    },
    onSuccess: async () => {
      setFeedback(
        `已通过并设为正式：镜头 ${shotId}，素材 ${artifactId}。下一步：${
          stage === "formal_keyframe" ? "可返回分镜生成视频" : "可进入剪辑或继续检查下一镜"
        }。`,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.review.summary(projectId, shotId, artifactId, reviewKind, stage),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.shot.reviewWorkbench(projectId, shotId),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.scene.summaries(projectId) }),
      ]);
    },
    onError: (error: unknown) => {
      setFeedback(
        `通过并设为正式失败：${error instanceof Error ? error.message : String(error)}。请重新读取状态后再操作，避免重复提交。`,
      );
    },
  });

  // A candidate can exist before its review does; without evidence no judgement
  // can be recorded, so the page offers the zero-cost review of this candidate.
  const requestEvidence = useMutation({
    mutationFn: () => createReviewEvidence(projectId, shotId, { artifact_id: artifactId, stage }),
    onSuccess: async () => {
      setFeedback("已提交本候选的审查证据生成，完成后即可判断。");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.review.summary(projectId, shotId, artifactId, reviewKind, stage),
      });
    },
    onError: (error: unknown) => {
      setFeedback(`生成审查证据失败：${error instanceof Error ? error.message : String(error)}`);
    },
  });

  const data: ReviewSummaryRead | undefined = summary.data;
  const blocker = reviewBlockerLabel(data?.blocked_reason ?? null);
  const hasEvidence = Boolean(data?.review_node_run_id && data?.review_artifact_id);

  return (
    <section className="qc-review-decision" data-testid={`review-decision-${reviewKind}`}>
      <h3>{title}</h3>
      {summary.isError && (
        <p className="flash err" data-testid="review-summary-error" role="alert">
          无法读取审查状态。
        </p>
      )}
      <dl className="qc-review-decision-facts">
        <dt>自动检查</dt>
        <dd data-testid="review-machine-status">
          {reviewMachineStatusLabel(data?.machine_status ?? null)}
        </dd>
        <dt>人工决定</dt>
        <dd data-testid="review-current-decision">
          {data?.decision === "approved"
            ? "已通过"
            : data?.decision === "rejected"
              ? "已拒绝"
              : data?.decision === "demo_confirmed"
                ? "仅演示流程确认（未质检放行）"
                : "尚未判断"}
        </dd>
      </dl>
      {data?.decision_reason && (
        <p className="muted" data-testid="review-decision-reason">
          理由：{data.decision_reason}
        </p>
      )}
      {blocker && (
        <p className="flash err" data-testid="review-blocker" role="status">
          {blocker}
        </p>
      )}

      <label>
        判断理由（必填）
        <input
          aria-label={`${title}判断理由`}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          disabled={decide.isPending}
        />
      </label>
      <div className="qc-unsaved-actions">
        {(stage === "formal_keyframe" || stage === "formal_video") && (
          <button
            type="button"
            data-testid={`review-approve-and-formal-${reviewKind}`}
            disabled={
              decide.isPending ||
              approveAndFormal.isPending ||
              !hasEvidence ||
              (data?.decision !== "approved" && !reason.trim())
            }
            onClick={() => approveAndFormal.mutate()}
          >
            {approveAndFormal.isPending ? "正在通过并设置…" : "通过并设为正式"}
          </button>
        )}
        <button
          type="button"
          data-testid={`review-approve-${reviewKind}`}
          disabled={
            approveAndFormal.isPending || decide.isPending || !reason.trim() || !hasEvidence
          }
          onClick={() => decide.mutate("approved")}
        >
          人工通过此素材
        </button>
        <button
          type="button"
          className="secondary"
          data-testid={`review-reject-${reviewKind}`}
          disabled={
            approveAndFormal.isPending || decide.isPending || !reason.trim() || !hasEvidence
          }
          onClick={() => decide.mutate("rejected")}
        >
          人工拒绝此素材
        </button>
        <button
          type="button"
          className="secondary"
          data-testid={`review-demo-confirm-${reviewKind}`}
          disabled={
            approveAndFormal.isPending || decide.isPending || !reason.trim() || !hasEvidence
          }
          onClick={() => decide.mutate("demo_confirmed")}
        >
          仅确认演示流程（不放行）
        </button>
      </div>
      {!hasEvidence && (
        <>
          <p className="muted" data-testid="review-evidence-missing">
            当前素材还没有自动检查证据，无法记录人工决定；请先运行对应审查节点。
          </p>
          <div className="qc-unsaved-actions">
            <button
              type="button"
              data-testid={`review-request-evidence-${reviewKind}`}
              onClick={() => requestEvidence.mutate()}
              disabled={requestEvidence.isPending}
            >
              {requestEvidence.isPending ? "正在提交…" : "生成本候选的审查证据"}
            </button>
          </div>
        </>
      )}
      {feedback && (
        <p className="muted" data-testid="review-decision-feedback" role="status">
          {feedback}
        </p>
      )}
      <p className="muted">
        “通过并设为正式”用于连续审片；下方单独通过 /
        拒绝保留为高级模式。自动检查只是初筛，不能替代人工判断。
      </p>
    </section>
  );
}
