import { artifactContentUrl } from "../../lib/api";
import type { ShotLite } from "./api";

type CinematicCanvasProps = {
  projectId: string;
  shot: ShotLite | null;
};

/** Central canvas: placeholder / keyframe / video player based on state. */
export function CinematicCanvas({ projectId, shot }: CinematicCanvasProps) {
  const keyframeId = shot?.formal_keyframe_artifact_id ?? null;
  const videoId = shot?.formal_video_artifact_id ?? null;
  return (
    <div className="qc-cinematic-canvas" data-testid="cinematic-canvas">
      {!shot ? (
        <p className="qc-canvas-empty">选择左侧镜头开始导演构图。</p>
      ) : videoId ? (
        <video
          controls
          preload="metadata"
          src={artifactContentUrl(projectId, videoId)}
          data-testid="shot-video-player"
        />
      ) : keyframeId ? (
        <img
          src={artifactContentUrl(projectId, keyframeId)}
          alt={`#${shot.shot_number} 关键帧`}
          data-testid="shot-keyframe"
        />
      ) : (
        <div className="qc-canvas-empty" data-testid="shot-placeholder">
          <h3>#{shot.shot_number} 导演构图预览</h3>
          <p>{shot.visual_description || "尚未生成关键帧。"}</p>
          <p className="qc-canvas-hint" data-testid="no-formal-result">
            尚未选择正式结果
          </p>
        </div>
      )}
    </div>
  );
}
