import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "../../lib/queryKeys";
import { fetchReviewSummary, type ReviewDecisionKind, type ReviewStage } from "./reviewDecisionApi";

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
  const summary = useQuery({
    queryKey: queryKeys.review.summary(projectId, shotId, artifactId, reviewKind, stage),
    queryFn: () => fetchReviewSummary(projectId, shotId, artifactId, reviewKind, stage),
    enabled: projectId !== "demo" && Boolean(shotId) && Boolean(artifactId),
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
      <p className="muted" data-testid="review-evidence-empty">
        暂无自动抽帧检查结果，可直接播放下方视频并进行人工审片。
      </p>
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
