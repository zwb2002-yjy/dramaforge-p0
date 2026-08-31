import type { ShotLite } from "./api";

type ShotStripProps = {
  shots: ShotLite[];
  selectedShotId: string | null;
  onSelectShot: (shotId: string) => void;
};

/** Scene-local Shot navigation for the workspace's left rail. */
export function ShotStrip({ shots, selectedShotId, onSelectShot }: ShotStripProps) {
  return (
    <ol
      className="qc-shot-strip"
      data-testid="shot-strip"
      data-selected-shot-id={selectedShotId ?? undefined}
      aria-label="镜头序列"
    >
      {shots.map((shot) => (
        <li key={shot.id}>
          <button
            type="button"
            className={shot.id === selectedShotId ? "active" : undefined}
            aria-pressed={shot.id === selectedShotId}
            onClick={() => onSelectShot(shot.id)}
          >
            <strong>#{shot.shot_number}</strong>
            <span>{shot.shot_type}</span>
            {shot.formal_keyframe_artifact_id && <em>关键帧</em>}
            {shot.formal_video_artifact_id && <em>视频</em>}
          </button>
        </li>
      ))}
    </ol>
  );
}
