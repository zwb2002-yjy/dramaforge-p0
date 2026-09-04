/**
 * VideoReviewTimeline (P6-03 / 03 §55).
 *
 * Renders video review annotations: time points, time ranges and text notes.
 * Times are in seconds; the timeline spans [0, durationSeconds].
 */

export interface VideoAnnotation {
  id: string;
  startSeconds: number;
  endSeconds?: number | null;
  note: string;
}

export interface VideoReviewTimelineProps {
  durationSeconds: number;
  annotations: VideoAnnotation[];
}

export function VideoReviewTimeline({ durationSeconds, annotations }: VideoReviewTimelineProps) {
  const duration = Math.max(durationSeconds, 0.001);
  return (
    <div data-testid="video-review-timeline" className="space-y-1 text-sm">
      <div className="relative h-8 w-full rounded border bg-gray-100">
        {annotations.map((annotation) => {
          const startPct = Math.min(100, (annotation.startSeconds / duration) * 100);
          const endSeconds = annotation.endSeconds ?? annotation.startSeconds;
          const widthPct = Math.max(
            1.5,
            ((Math.min(endSeconds, duration) - annotation.startSeconds) / duration) * 100,
          );
          return (
            <div
              key={annotation.id}
              data-testid="timeline-annotation"
              className="absolute top-1 h-6 rounded bg-amber-400"
              style={{ left: `${startPct}%`, width: `${widthPct}%` }}
              title={annotation.note}
            />
          );
        })}
      </div>
      <ul className="space-y-1">
        {annotations.map((annotation) => (
          <li key={annotation.id} className="text-xs">
            <span className="font-mono">
              {annotation.startSeconds.toFixed(2)}s
              {annotation.endSeconds != null ? `–${annotation.endSeconds.toFixed(2)}s` : ""}
            </span>
            ：{annotation.note || "（无说明）"}
          </li>
        ))}
      </ul>
    </div>
  );
}
