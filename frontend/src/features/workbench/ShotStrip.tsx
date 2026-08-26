import type { ShotLite } from "./api";

type ShotStripProps = {
  shots: ShotLite[];
  selectedShotId: string | null;
  onSelectShot: (shotId: string) => void;
};

/** Left/bottom shot sequence strip for the scene workspace. */
export function ShotStrip({ shots, selectedShotId, onSelectShot }: ShotStripProps) {
  return (
    <ol className="qc-shot-strip" data-testid="shot-strip" aria-label="镜头序列">
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
