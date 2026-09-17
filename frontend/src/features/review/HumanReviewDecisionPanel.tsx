import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { queryKeys } from "../../lib/queryKeys";
import { reviewBlockerLabel, reviewMachineStatusLabel } from "./reviewLabels";
import {
  createReviewDecision,
  fetchReviewSummary,
  type ReviewDecisionWrite,
  type ReviewStage,
  type ReviewSummaryRead,
} from "./reviewDecisionApi";

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
    enabled: projectId !== "demo" && Boolean(shotId) && Boolean(artifactId),
  });

  const decide = useMutation({
    mutationFn: (decision: "approved" | "rejected") =>
      createReviewDecision(
        projectId,
        shotId,
        {
          artifact_id: artifactId,
          review_node_run_id: summary.data?.review_node_run_id ?? "",
          review_kind: reviewKind,
          decision,
          reason: reason.trim(),
          expected_shot_version: shotVersion,
        },
        requestKey.current,
      ),
    onSuccess: async (saved) => {
      // A new decision is a new operation: the next submit must use a new key.
      requestKey.current = `review:${globalThis.crypto.randomUUID()}`;
      setFeedback(saved.decision === "approved" ? "已记录人工通过。" : "已记录人工拒绝。");
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

  const data: ReviewSummaryRead | undefined = summary.data;
  const blocker = reviewBlockerLabel(data?.blocked_reason ?? null);
  const hasEvidence = Boolean(data?.review_node_run_id);

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
        <button
          type="button"
          data-testid={`review-approve-${reviewKind}`}
          disabled={decide.isPending || !reason.trim() || !hasEvidence}
          onClick={() => decide.mutate("approved")}
        >
          人工通过此素材
        </button>
        <button
          type="button"
          className="secondary"
          data-testid={`review-reject-${reviewKind}`}
          disabled={decide.isPending || !reason.trim() || !hasEvidence}
          onClick={() => decide.mutate("rejected")}
        >
          人工拒绝此素材
        </button>
      </div>
      {!hasEvidence && (
        <p className="muted" data-testid="review-evidence-missing">
          当前素材还没有自动检查证据，无法记录人工决定；请先运行对应审查节点。
        </p>
      )}
      {feedback && (
        <p className="muted" data-testid="review-decision-feedback" role="status">
          {feedback}
        </p>
      )}
      <p className="muted">人工通过只记录判断；设为正式仍是另一个明确动作。</p>
    </section>
  );
}
