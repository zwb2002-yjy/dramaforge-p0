import { useEffect, useRef } from "react";
import { artifactContentUrl } from "../../lib/api";
import type { EditableClip } from "./useTimelineDraft";
import { timelineCopy as copy } from "./timelineCopy";
import "./editing-source-preview.css";

/** Read-only source playback; it never claims to render an unsaved composition. */
export function EditingSourcePreview({
  projectId,
  clips,
  selectedIndex,
}: {
  projectId: string;
  clips: EditableClip[];
  selectedIndex?: number;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const chosen = selectedIndex ?? 0;
  const index = Math.min(chosen, Math.max(0, clips.length - 1));
  const clip = clips[index];
  const artifactId = typeof clip?.artifact_id === "string" ? clip.artifact_id : null;
  useEffect(() => {
    const video = videoRef.current;
    return () => {
      if (video && !video.paused) video.pause();
    };
  }, [artifactId]);
  return (
    <section className="editing-source-preview" aria-label="剪辑素材预览">
      <header>
        <h2>{copy.source}</h2>
        <p>{copy.sourceNotice}</p>
      </header>
      {artifactId ? (
        <video
          key={artifactId}
          ref={videoRef}
          controls
          preload="metadata"
          src={artifactContentUrl(projectId, artifactId)}
          aria-label={`片段 ${index + 1} 原始视频预览`}
        />
      ) : (
        <p>暂无可播放的正式视频。请先在分镜中审查并选择正式版本。</p>
      )}
    </section>
  );
}
