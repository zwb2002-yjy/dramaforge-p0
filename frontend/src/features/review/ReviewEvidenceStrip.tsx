import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../lib/queryKeys";
import {
  createReviewEvidence,
  fetchReviewSummary,
  type ReviewDecisionKind,
  type ReviewStage,
} from "./reviewDecisionApi";

export function ReviewEvidenceStrip({
  projectId,
  shotId,
  artifactId,
  reviewKind,
  stage,
  onSelectTime,
}: {
  projectId: string;
  shotId: string;
  artifactId: string;
  reviewKind: ReviewDecisionKind;
  stage: ReviewStage;
  onSelectTime?: (seconds: number) => void;
}) {
  const queryClient = useQueryClient();
  const regenerate = useMutation({
    mutationFn: () =>
      createReviewEvidence(projectId, shotId, { artifact_id: artifactId, stage, force: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.review.summary(projectId, shotId, artifactId, reviewKind, stage),
      });
    },
  });
  const summary = useQuery({
    queryKey: queryKeys.review.summary(projectId, shotId, artifactId, reviewKind, stage),
    queryFn: () => fetchReviewSummary(projectId, shotId, artifactId, reviewKind, stage),
    enabled: Boolean(projectId) && Boolean(shotId) && Boolean(artifactId),
    refetchInterval: (query) =>
      regenerate.isSuccess && !(query.state.data?.evidence?.frames?.length ?? 0) ? 3000 : false,
  });
  const frames = [...(summary.data?.evidence?.frames ?? [])].sort(
    (left, right) => left.timestamp_seconds - right.timestamp_seconds,
  );
  if (summary.isLoading)
    return (
      <p className="muted" role="status">
        正在读取自动抽帧检查结果…
      </p>
    );
  if (summary.isError)
    return (
      <p className="flash err" role="alert">
        无法读取自动抽帧检查结果；仍可直接播放视频审片。
      </p>
    );
  if (frames.length === 0) {
    return (
      <div data-testid="review-evidence-empty">
        <p className="muted">暂无自动抽帧检查结果，可直接播放下方视频并进行人工审片。</p>
        {stage === "formal_video" && (
          <button type="button" disabled={regenerate.isPending} onClick={() => regenerate.mutate()}>
            {regenerate.isPending ? "正在重新抽取首中尾帧…" : "重新抽取首帧、中帧、尾帧"}
          </button>
        )}
        {regenerate.isError && <p role="alert">重新抽帧失败：{String(regenerate.error)}</p>}
      </div>
    );
  }
  return (
    <section
      className="director-frame-evidence"
      data-testid="review-evidence-strip"
      aria-label="视频证据"
    >
      <header>
        <strong>视频证据</strong>
        <span>{summary.data?.evidence?.sampling_version ?? "未标注采样版本"}</span>
      </header>
      <div>
        {frames.map((frame) => (
          <figure key={frame.sample_id} data-testid={`review-evidence-${frame.sample_id}`}>
            {frame.delivery_path ? (
              <button
                type="button"
                onClick={() => onSelectTime?.(frame.timestamp_seconds)}
                aria-label={`定位${frame.role} ${frame.timestamp_seconds}秒`}
              >
                <img src={frame.delivery_path} alt={`${frame.role}帧`} />
              </button>
            ) : (
              <div className="muted">证据不可用</div>
            )}
            <figcaption>
              {frame.role} · {frame.timestamp_seconds.toFixed(3)}s
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
