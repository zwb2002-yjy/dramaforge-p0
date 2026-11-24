import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { artifactContentUrl } from "../../lib/api";
import type { EditableClip } from "./useTimelineDraft";
import { timelineCopy as copy } from "./timelineCopy";
import { localClipVideo, publicCutUrl } from "./publicCutSource";
import { editingClipLabel } from "./clipPresentation";
import { Badge, SectionHeader } from "../../components/ui";
import "./editing-source-preview.css";

function sourceBounds(clip: EditableClip | undefined) {
  const start = Number(clip?.source_in_seconds ?? 0);
  return {
    start,
    end:
      clip?.source_out_seconds == null
        ? start + Number(clip?.duration_seconds ?? 0)
        : Number(clip.source_out_seconds),
  };
}

/** Read-only source playback; it never claims to render an unsaved composition. */
export function EditingSourcePreview({
  projectId,
  clips,
  selectedIndex,
  seekRequest,
  pauseRevision,
  onPosition,
}: {
  projectId: string;
  clips: EditableClip[];
  selectedIndex?: number;
  seekRequest?: { progress: number; revision: number };
  pauseRevision: number;
  onPosition?: (progress: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const chosen = selectedIndex ?? 0;
  const index = Math.min(chosen, Math.max(0, clips.length - 1));
  const clip = clips[index];
  const artifactId = localClipVideo(clip);
  const sourceUrl =
    publicCutUrl(projectId, clip, "source") ??
    (artifactId ? artifactContentUrl(projectId, artifactId) : undefined);
  useLayoutEffect(() => {
    const video = videoRef.current;
    if (video && !video.paused) video.pause();
  }, [pauseRevision, index, sourceUrl]);
  const positionSource = useCallback(() => {
    const video = videoRef.current;
    if (!video || video.readyState < 1 || !seekRequest || !Number.isFinite(seekRequest.progress))
      return;
    const { start, end } = sourceBounds(clip);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    const target = Math.max(
      0,
      Math.min(
        video.duration,
        start + Math.max(0, Math.min(1, seekRequest.progress)) * (end - start),
      ),
    );
    if (Math.abs(video.currentTime - target) > 0.001) video.currentTime = target;
  }, [clip, seekRequest]);
  useEffect(positionSource, [positionSource, sourceUrl]);
  useEffect(() => {
    const video = videoRef.current;
    return () => {
      if (video && !video.paused) video.pause();
    };
  }, [sourceUrl]);
  return (
    <section className="editing-source-preview" aria-label="剪辑素材预览">
      <SectionHeader title={clip ? editingClipLabel(clip, index) : copy.source}>
        <Badge>{copy.sourceNotice}</Badge>
      </SectionHeader>
      {sourceUrl ? (
        <video
          key={sourceUrl}
          ref={videoRef}
          controls
          preload="metadata"
          onLoadedMetadata={positionSource}
          onTimeUpdate={(event) => {
            const video = event.currentTarget;
            const { start, end } = sourceBounds(clip);
            if (Number.isFinite(start) && Number.isFinite(end) && end > start)
              onPosition?.(Math.max(0, Math.min(1, (video.currentTime - start) / (end - start))));
          }}
          src={sourceUrl}
          aria-label={`片段 ${index + 1} 原始视频预览`}
        />
      ) : (
        <p>暂无可播放的正式视频。请先在分镜中审查并选择正式版本。</p>
      )}
    </section>
  );
}
