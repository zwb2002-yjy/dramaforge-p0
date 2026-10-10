import { useState } from "react";
import { Button, Checkbox, Field, Input, Select } from "../../components/ui";
import type { EditableClip } from "./useTimelineDraft";
import type { TimelinePreviewRead } from "./api";
import { timelineGeometry } from "./timelineGeometry";
import { TimelineCropHandle } from "./TimelineCropHandle";
import { timelineCopy as copy } from "./timelineCopy";
import "./editing-timeline.css";

/** Linked media lanes over the sole EditSession draft; zoom and gestures are UI state. */
export function EditingTimeline({
  clips,
  selectedIndex,
  onSelectClip,
  onReorder,
  onSeek,
  onUpdateClip,
  plan,
  playheadMs = 0,
}: {
  clips: EditableClip[];
  selectedIndex: number;
  onSelectClip: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onSeek: (milliseconds: number) => void;
  onUpdateClip?: (index: number, clip: EditableClip) => void;
  plan?: TimelinePreviewRead | null;
  playheadMs?: number;
}) {
  const [dragged, setDragged] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const geometry = timelineGeometry(clips, plan);
  const { items, durationMs: total } = geometry;
  const selected = clips[selectedIndex];
  const pixels = (milliseconds: number) =>
    `calc(${(milliseconds / 1000) * zoom} * var(--df-timeline-pixels-per-second))`;
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
        <p role={geometry.valid ? "status" : "alert"}>
          {!geometry.valid
            ? copy.invalidGeometry
            : geometry.compiled
              ? copy.geometryCompiled
              : copy.geometryDraft}
        </p>
      </header>
      <div className="editing-timeline-tools">
        <Field>
          {copy.zoom}
          <Select
            aria-label={copy.zoom}
            value={zoom}
            onChange={(event) => setZoom(Number(event.currentTarget.value))}
          >
            <option value={0.5}>50%</option>
            <option value={1}>100%</option>
            <option value={2}>200%</option>
          </Select>
        </Field>
        <Field>
          时间线播放头（秒）
          <Input
            type="range"
            min={0}
            max={total / 1000}
            step={0.001}
            value={Math.min(total, playheadMs) / 1000}
            disabled={!geometry.valid}
            onChange={(event) => onSeek(Number(event.target.value) * 1000)}
            data-testid="editing-playhead"
          />
        </Field>
      </div>
      {onUpdateClip && selected && (
        <div className="editing-timeline-tools" aria-label={`片段 ${selectedIndex + 1} 轨道操作`}>
          <Field>
            <Checkbox
              checked={selected.muted === true}
              onChange={(event) =>
                onUpdateClip(selectedIndex, { ...selected, muted: event.currentTarget.checked })
              }
            />
            {copy.muteToggle}
          </Field>
          <Field>
            配音音量
            <Input
              type="range"
              min={0}
              max={1}
              step={0.01}
              data-testid="editing-track-volume"
              value={Number(selected.audio_volume ?? 1)}
              onChange={(event) =>
                onUpdateClip(selectedIndex, {
                  ...selected,
                  audio_volume: Number(event.currentTarget.value),
                })
              }
            />
          </Field>
          <Field>
            <Checkbox
              checked={selected.subtitle_enabled !== false}
              onChange={(event) =>
                onUpdateClip(selectedIndex, {
                  ...selected,
                  subtitle_enabled: event.currentTarget.checked,
                })
              }
            />
            {copy.subtitleToggle}
          </Field>
        </div>
      )}
      <div className="editing-timeline-scroll">
        <div className="editing-time-ruler" aria-label="时间刻度">
          <div className="editing-track-body" style={{ width: pixels(total) }}>
            {items.map((item, index) => (
              <span key={String(clips[index].id ?? index)} style={{ left: pixels(item.startMs) }}>
                {(item.startMs / 1000).toFixed(3)} s
              </span>
            ))}
            <span style={{ left: pixels(total) }} data-testid="editing-timeline-duration">
              {(total / 1000).toFixed(3)} s
            </span>
          </div>
        </div>
        <nav
          aria-label="时间线片段预览"
          className="editing-timeline-lane"
          data-testid="editing-visual-track"
        >
          <strong>{copy.video}</strong>
          <div className="editing-track-body" style={{ width: pixels(total) }}>
            {clips.map((clip, index) => (
              <div
                key={String(clip.id ?? index)}
                className="editing-timeline-cell"
                data-overlap-ms={items[index].overlapMs}
                style={{
                  left: pixels(items[index].startMs),
                  width: pixels(items[index].durationMs),
                }}
              >
                <Button
                  data-testid={`editing-track-clip-${index}`}
                  className="editing-timeline-clip"
                  aria-pressed={selectedIndex === index}
                  draggable
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
                    {(items[index].durationMs / 1000).toFixed(3)} s · 入点{" "}
                    {String(clip.source_in_seconds ?? 0)}
                  </small>
                  {items[index].overlapMs > 0 && (
                    <small>淡化 {(items[index].overlapMs / 1000).toFixed(3)} s</small>
                  )}
                </Button>
                {onUpdateClip &&
                  (["in", "out"] as const).map((edge) => (
                    <TimelineCropHandle
                      key={edge}
                      clip={clip}
                      index={index}
                      edge={edge}
                      onCrop={(cropped) => {
                        onSelectClip(index);
                        onUpdateClip(index, cropped);
                      }}
                    />
                  ))}
              </div>
            ))}
          </div>
        </nav>
        {(["audio", "subtitles"] as const).map((lane) => (
          <div
            key={lane}
            className="editing-timeline-lane"
            aria-label={copy[lane]}
            data-testid={`editing-${lane}-track`}
          >
            <strong>{copy[lane]}</strong>
            <div className="editing-track-body" style={{ width: pixels(total) }}>
              {clips.map((clip, index) => (
                <Button
                  key={String(clip.id ?? index)}
                  className="editing-timeline-clip editing-timeline-cell"
                  style={{
                    left: pixels(items[index].startMs),
                    width: pixels(items[index].durationMs),
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
          </div>
        ))}
      </div>
    </section>
  );
}
