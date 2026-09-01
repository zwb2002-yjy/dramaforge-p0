import { artifactContentUrl } from "../../lib/api";
import type { ShotLite } from "./api";

type ShotStripProps = {
  projectId?: string;
  shots: ShotLite[];
  selectedShotId: string | null;
  onSelectShot: (shotId: string) => void;
  traceByShot?: Record<string, unknown[]>;
};

const FAILED_STATUSES = new Set(["failed", "error", "cancelled", "canceled"]);

function hasTraceRisk(trace: unknown[]): boolean {
  return trace.some((value) => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const row = value as Record<string, unknown>;
    const status = typeof row.status === "string" ? row.status.toLowerCase() : "";
    return Boolean(row.error_code) || FAILED_STATUSES.has(status);
  });
}

function durationLabel(value: ShotLite["duration_seconds"]): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed}s` : `${value || "—"}s`;
}

/** Bottom horizontal storyboard / timeline hybrid for one Scene. */
export function ShotStrip({
  projectId,
  shots,
  selectedShotId,
  onSelectShot,
  traceByShot = {},
}: ShotStripProps) {
  return (
    <section className="qc-shot-strip-panel" data-testid="shot-strip-panel" aria-label="镜头时间条">
      <header className="qc-shot-strip-header">
        <div>
          <span className="director-stage-kicker">Storyboard / timeline</span>
          <strong>场景镜头</strong>
        </div>
        <span>{shots.length} 镜</span>
      </header>
      <ol
        className="qc-shot-strip"
        data-testid="shot-strip"
        data-layout="bottom-horizontal"
        data-selected-shot-id={selectedShotId ?? undefined}
        aria-label="镜头序列"
      >
        {shots.map((shot) => {
          const selected = shot.id === selectedShotId;
          const risk = hasTraceRisk(traceByShot[shot.id] ?? []);
          return (
            <li key={shot.id}>
              <button
                type="button"
                className={selected ? "active" : undefined}
                aria-pressed={selected}
                aria-label={`#${shot.shot_number} ${shot.shot_type} ${durationLabel(shot.duration_seconds)}`}
                onClick={() => onSelectShot(shot.id)}
                data-testid={`shot-strip-card-${shot.id}`}
              >
                <span className="qc-shot-strip-thumb" data-testid={`shot-strip-thumb-${shot.id}`}>
                  {projectId && shot.formal_keyframe_artifact_id ? (
                    <img
                      src={artifactContentUrl(projectId, shot.formal_keyframe_artifact_id)}
                      alt={`#${shot.shot_number} 正式关键帧`}
                    />
                  ) : (
                    <span aria-hidden="true">镜{String(shot.shot_number).padStart(2, "0")}</span>
                  )}
                </span>
                <span className="qc-shot-strip-copy">
                  <strong>#{shot.shot_number}</strong>
                  <span>{shot.shot_type}</span>
                  <small>{durationLabel(shot.duration_seconds)}</small>
                </span>
                <span className="qc-shot-strip-status" aria-label="正式状态">
                  <em className={shot.formal_keyframe_artifact_id ? "ready" : undefined}>
                    关键帧 {shot.formal_keyframe_artifact_id ? "已确认" : "待确认"}
                  </em>
                  <em className={shot.formal_video_artifact_id ? "ready" : undefined}>
                    视频 {shot.formal_video_artifact_id ? "已确认" : "待确认"}
                  </em>
                  {risk && <em className="risk">生产失败风险</em>}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
