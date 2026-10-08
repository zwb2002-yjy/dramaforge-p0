import { useState } from "react";
import { Button } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import type { EditableClip } from "./useTimelineDraft";
import "./editing-source-preview.css";

/** Read-only source playback; it never claims to render an unsaved composition. */
export function EditingSourcePreview({
  projectId,
  clips,
  selectedIndex,
  onSelectClip,
}: {
  projectId: string;
  clips: EditableClip[];
  selectedIndex?: number;
  onSelectClip?: (index: number) => void;
}) {
  const [localSelected, setLocalSelected] = useState(0);
  const chosen = selectedIndex ?? localSelected;
  const index = Math.min(chosen, Math.max(0, clips.length - 1));
  const selectClip = (next: number) => {
    if (onSelectClip) onSelectClip(next);
    else setLocalSelected(next);
  };
  const clip = clips[index];
  const artifactId = typeof clip?.artifact_id === "string" ? clip.artifact_id : null;
  return (
    <section className="editing-source-preview" aria-label="剪辑素材预览">
      <header>
        <h2>素材预览</h2>
        <p>当前仅预览原始片段；裁剪、转场、字幕和音频效果以导出成片为准。</p>
      </header>
      {artifactId ? (
        <video
          key={artifactId}
          controls
          preload="metadata"
          src={artifactContentUrl(projectId, artifactId)}
          aria-label={`片段 ${index + 1} 原始视频预览`}
        />
      ) : (
        <p>暂无可播放的正式视频。请先在分镜中审查并选择正式版本。</p>
      )}
      <nav
        aria-label="时间线片段预览"
        className="editing-visual-track"
        data-testid="editing-visual-track"
      >
        {clips.map((item, i) => {
          const duration = Number(item.duration_seconds);
          return (
            <div
              key={String(item.id ?? i)}
              className="editing-track-segment"
              style={{ flexGrow: Number.isFinite(duration) && duration > 0 ? duration : 1 }}
            >
              <Button
                className="editing-track-clip"
                data-testid={`editing-track-clip-${i}`}
                aria-pressed={index === i}
                onClick={() => selectClip(i)}
              >
                <span>片段 {i + 1}</span>
                <small>{String(item.duration_seconds ?? "—")} 秒</small>
              </Button>
            </div>
          );
        })}
      </nav>
    </section>
  );
}
