import { useState } from "react";
import { Button } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import type { EditableClip } from "./useTimelineDraft";
import "./editing-source-preview.css";

/** Read-only source playback; it never claims to render an unsaved composition. */
export function EditingSourcePreview({
  projectId,
  clips,
}: {
  projectId: string;
  clips: EditableClip[];
}) {
  const [selected, setSelected] = useState(0);
  const index = Math.min(selected, Math.max(0, clips.length - 1));
  const clip = clips[index];
  const artifactId = typeof clip?.artifact_id === "string" ? clip.artifact_id : null;
  return (
    <section className="editing-source-preview" aria-label="剪辑素材预览">
      <header>
        <h2>画面预览</h2>
        <p>播放原始片段。时长、字幕与转场以保存后导出的成片为准。</p>
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
      <nav aria-label="时间线片段预览">
        {clips.map((item, i) => (
          <Button
            key={String(item.id ?? i)}
            aria-pressed={index === i}
            onClick={() => setSelected(i)}
          >
            片段 {i + 1} · {String(item.duration_seconds ?? "—")} 秒
          </Button>
        ))}
      </nav>
    </section>
  );
}
