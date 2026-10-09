import { useState } from "react";
import { Button, Field, Input } from "../../components/ui";
import type { EditableClip } from "./useTimelineDraft";
import { timelineCopy as copy } from "./timelineCopy";
import "./editing-timeline.css";

/** Three linked edit lanes over the sole EditSession draft; no parallel timeline store. */
export function EditingTimeline({
  clips,
  selectedIndex,
  onSelectClip,
  onReorder,
  onSeek,
  playheadMs = 0,
}: {
  clips: EditableClip[];
  selectedIndex: number;
  onSelectClip: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onSeek: (milliseconds: number) => void;
  playheadMs?: number;
}) {
  const [dragged, setDragged] = useState<number | null>(null);
  const durations = clips.map((clip) =>
    Math.max(1, Math.round((Number(clip.duration_seconds) || 0) * 1000)),
  );
  const total = durations.reduce((sum, value) => sum + value, 0);
  const reorder = (from: number, to: number) => {
    if (from !== to && from >= 0 && to >= 0 && to < clips.length) {
      onSelectClip(from);
      onReorder(from, to);
    }
    setDragged(null);
  };
  return (
    <section className="editing-timeline" aria-label={copy.timeline}>
      <header>
        <h2>{copy.timeline}</h2>
        <p>{copy.dragHint}</p>
      </header>
      <Field>
        时间线播放头（秒）
        <Input
          type="range"
          min={0}
          max={total / 1000}
          step={0.001}
          value={Math.min(total, playheadMs) / 1000}
          onChange={(event) => onSeek(Number(event.target.value) * 1000)}
          data-testid="editing-playhead"
        />
      </Field>
      <div className="editing-timeline-scroll">
        <div className="editing-time-ruler" aria-label="时间刻度">
          {durations.map((duration, index) => (
            <div
              key={String(clips[index].id ?? index)}
              style={{ width: `calc(${duration / 1000} * var(--df-timeline-pixels-per-second))` }}
            >
              {(durations.slice(0, index).reduce((sum, value) => sum + value, 0) / 1000).toFixed(3)}{" "}
              s
            </div>
          ))}
          <span>{(total / 1000).toFixed(3)} s</span>
        </div>
        <nav
          aria-label="时间线片段预览"
          className="editing-timeline-lane"
          data-testid="editing-visual-track"
        >
          <strong>{copy.video}</strong>
          {clips.map((clip, index) => (
            <Button
              key={String(clip.id ?? index)}
              data-testid={`editing-track-clip-${index}`}
              className="editing-timeline-clip"
              aria-pressed={selectedIndex === index}
              draggable
              style={{
                width: `calc(${durations[index] / 1000} * var(--df-timeline-pixels-per-second))`,
              }}
              onClick={() => onSelectClip(index)}
              onDragStart={(event) => {
                setDragged(index);
                event.dataTransfer.setData("text/plain", String(index));
                event.dataTransfer.effectAllowed = "move";
              }}
              onDragOver={(event) => {
                if (dragged !== null) event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                if (dragged !== null) reorder(dragged, index);
              }}
              onDragEnd={() => setDragged(null)}
              onKeyDown={(event) => {
                if (event.altKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
                  event.preventDefault();
                  reorder(index, index + (event.key === "ArrowLeft" ? -1 : 1));
                }
              }}
            >
              <span>片段 {index + 1}</span>
              <small>
                {(durations[index] / 1000).toFixed(3)} s · 入点{" "}
                {String(clip.source_in_seconds ?? 0)}
              </small>
            </Button>
          ))}
        </nav>
        {(["audio", "subtitles"] as const).map((lane) => (
          <div
            key={lane}
            className="editing-timeline-lane"
            aria-label={copy[lane]}
            data-testid={`editing-${lane}-track`}
          >
            <strong>{copy[lane]}</strong>
            {clips.map((clip, index) => (
              <Button
                key={String(clip.id ?? index)}
                className="editing-timeline-clip"
                style={{
                  width: `calc(${durations[index] / 1000} * var(--df-timeline-pixels-per-second))`,
                }}
                aria-pressed={selectedIndex === index}
                onClick={() => onSelectClip(index)}
              >
                {lane === "audio"
                  ? clip.muted === true
                    ? copy.mute
                    : clip.audio_id
                      ? `音频 · ${Math.round(Number(clip.audio_volume ?? 1) * 100)}%`
                      : copy.defaultAudio
                  : clip.subtitle_enabled === false
                    ? copy.noSubtitle
                    : String(clip.subtitle ?? "沿用镜头字幕") || copy.noSubtitle}
              </Button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
