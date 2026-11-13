import { useEffect, useRef, useState } from "react";
import { Film, Mic, Type } from "lucide-react";
import { useTimelineReorder } from "./useTimelineReorder";
import { Checkbox, Field, InputNumber, Select, Slider } from "../../components/ui";
import type { EditableClip } from "./useTimelineDraft";
import type { TimelinePreviewRead } from "./api";
import { timelineGeometry } from "./timelineGeometry";
import { TimelineCropHandle } from "./TimelineCropHandle";
import { timelineCopy as copy } from "./timelineCopy";
import { editingClipLabel, timelineTime } from "./clipPresentation";
import { EditingClipThumbnail } from "./EditingClipThumbnail";
import "./editing-timeline.css";

/** Linked media lanes over the sole EditSession draft; zoom and gestures are UI state. */
export function EditingTimeline({
  projectId,
  clips,
  selectedIndex,
  onSelectClip,
  onReorder,
  onSeek,
  onUpdateClip,
  onInteractionStart,
  plan,
  playheadMs = 0,
}: {
  projectId: string;
  clips: EditableClip[];
  selectedIndex: number;
  onSelectClip: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onSeek: (milliseconds: number) => void;
  onUpdateClip?: (index: number, clip: EditableClip) => void;
  onInteractionStart?: () => void;
  plan?: TimelinePreviewRead | null;
  playheadMs?: number;
}) {
  const [zoom, setZoom] = useState("1");
  const scrollRef = useRef<HTMLDivElement>(null);
  const reorderGesture = useTimelineReorder({
    clips,
    scroller: scrollRef,
    onSelect: onSelectClip,
    onReorder,
    onInteractionStart,
  });
  const [viewport, setViewport] = useState({ width: 0, label: 0, baseScale: 0 });
  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const measure = () => {
      const style = getComputedStyle(element);
      const label = parseFloat(style.getPropertyValue("--df-timeline-label-width"));
      const lane = element.querySelector(".editing-timeline-lane");
      const gap = lane ? parseFloat(getComputedStyle(lane).columnGap) : 0;
      setViewport({
        width: Math.max(0, element.clientWidth - label - gap),
        label: label + gap,
        baseScale: parseFloat(style.getPropertyValue("--df-timeline-pixels-per-second")),
      });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const scroller = scrollRef.current;
    const selected = scroller?.querySelector(`[data-testid="editing-track-clip-${selectedIndex}"]`);
    if (!scroller || !selected) return;
    const bounds = scroller.getBoundingClientRect();
    const clipBounds = selected.getBoundingClientRect();
    if (clipBounds.left < bounds.left + viewport.label)
      scroller.scrollLeft += clipBounds.left - bounds.left - viewport.label;
    else if (clipBounds.right > bounds.right)
      scroller.scrollLeft += clipBounds.right - bounds.right;
  }, [selectedIndex, zoom, viewport]);
  const geometry = timelineGeometry(clips, plan);
  const { items, durationMs: total } = geometry;
  const selected = clips[selectedIndex];
  const pixels = (milliseconds: number) =>
    zoom === "fit" && viewport.width > 0 && total > 0
      ? `${(milliseconds / total) * viewport.width}px`
      : `calc(${(milliseconds / 1000) * (zoom === "fit" ? 1 : Number(zoom))} * var(--df-timeline-pixels-per-second))`;
  const scale =
    zoom === "fit" ? viewport.width / (total / 1000) : viewport.baseScale * Number(zoom);
  const tickSeconds = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((step) => step * scale >= 80) ?? 600;
  const ticks = Array.from(
    { length: Math.ceil(total / 1000 / tickSeconds) },
    (_, index) => index * tickSeconds * 1000,
  );
  const reorder = (from: number, to: number) => {
    if (from !== to && from >= 0 && to >= 0 && to < clips.length) {
      onSelectClip(from);
      onReorder(from, to);
    }
  };
  return (
    <section
      className="editing-timeline"
      aria-label={copy.timeline}
      data-compact={zoom === "fit" || Number(zoom) < 1}
    >
      <header>
        <div>
          <h2>
            {copy.timeline}{" "}
            <small>
              {clips.length} {copy.totalClips}
            </small>
          </h2>
          <p>{copy.dragHint}</p>
        </div>
        <output className="editing-timeline-timecode" aria-label={copy.position}>
          {timelineTime(Math.min(total, playheadMs))} <span>/ {timelineTime(total)}</span>
        </output>
      </header>
      <div className="editing-timeline-tools">
        <p className="editing-geometry-status" role={geometry.valid ? "status" : "alert"}>
          {!geometry.valid
            ? copy.invalidGeometry
            : geometry.compiled
              ? copy.geometryCompiled
              : copy.geometryDraft}
        </p>
        <Field>
          {copy.zoom}
          <Select aria-label={copy.zoom} value={zoom} onChange={(event) => setZoom(event)}>
            <option value="fit">{copy.fit}</option>
            <option value={0.25}>25%</option>
            <option value={0.5}>50%</option>
            <option value={1}>100%</option>
            <option value={2}>200%</option>
            <option value={4}>400%</option>
          </Select>
        </Field>
        <Field>
          {copy.playhead}
          <InputNumber
            aria-label={copy.playhead}
            min={0}
            max={total / 1000}
            step={0.001}
            precision={3}
            value={Number((Math.min(total, playheadMs) / 1000).toFixed(3))}
            disabled={!geometry.valid}
            onChange={(value) => {
              if (value !== null) onSeek(value * 1000);
            }}
            id="editing-playhead"
          />
        </Field>
      </div>
      {onUpdateClip && selected && (
        <div className="editing-timeline-tools" aria-label={`片段 ${selectedIndex + 1} 轨道操作`}>
          <span className="editing-selected-label">
            {copy.selected} · {editingClipLabel(selected, selectedIndex)}
          </span>
          <Field>
            <Checkbox
              checked={selected.muted === true}
              onChange={(event) =>
                onUpdateClip(selectedIndex, { ...selected, muted: event.target.checked })
              }
            />
            {copy.muteToggle}
          </Field>
          <Field>
            {copy.volume}
            <Slider
              ariaLabelForHandle={copy.volume}
              min={0}
              max={1}
              step={0.01}
              id="editing-track-volume"
              value={Number(selected.audio_volume ?? 1)}
              onChange={(value) =>
                onUpdateClip(selectedIndex, {
                  ...selected,
                  audio_volume: value,
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
                  subtitle_enabled: event.target.checked,
                })
              }
            />
            {copy.subtitleToggle}
          </Field>
        </div>
      )}
      <div className="editing-timeline-scroll" ref={scrollRef}>
        <div
          className="editing-timeline-content"
          style={{
            width: `calc(${pixels(total)} + var(--df-timeline-label-width) + var(--df-space-1))`,
          }}
        >
          <div className="editing-time-ruler" aria-label="时间刻度">
            <button
              type="button"
              className="editing-track-body editing-ruler-seek"
              style={{ width: pixels(total) }}
              aria-label={copy.seekRuler}
              disabled={!geometry.valid || total === 0}
              onClick={(event) => {
                const rect = event.currentTarget.getBoundingClientRect();
                if (rect.width > 0)
                  onSeek(
                    Math.round(
                      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * total,
                    ),
                  );
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                  event.preventDefault();
                  onSeek(
                    Math.max(
                      0,
                      Math.min(total, playheadMs + (event.key === "ArrowLeft" ? -100 : 100)),
                    ),
                  );
                } else if (event.key === "Home" || event.key === "End") {
                  event.preventDefault();
                  onSeek(event.key === "Home" ? 0 : total);
                }
              }}
            >
              {ticks
                .filter((value) => total - value > tickSeconds * 500)
                .map((value) => (
                  <span key={value} style={{ left: pixels(value) }} aria-hidden="true">
                    {timelineTime(value).slice(0, -4)}
                  </span>
                ))}
              <span
                className="editing-duration-mark"
                style={{ left: pixels(total) }}
                data-testid="editing-timeline-duration"
              >
                {(total / 1000).toFixed(3)} s
              </span>
            </button>
          </div>
          <nav
            aria-label="时间线片段预览"
            className="editing-timeline-lane"
            data-testid="editing-visual-track"
          >
            <strong>
              <Film size={16} aria-hidden="true" />
              {copy.video}
            </strong>
            <div className="editing-track-body" style={{ width: pixels(total) }}>
              {clips.map((clip, index) => (
                <div
                  key={String(clip.id ?? index)}
                  className="editing-timeline-cell"
                  data-editing-index={index}
                  data-dragging={reorderGesture.view?.from === index}
                  data-overlap-ms={items[index].overlapMs}
                  style={{
                    left: pixels(items[index].startMs),
                    width: pixels(items[index].durationMs),
                    transform: reorderGesture.offset(index),
                  }}
                >
                  <button
                    type="button"
                    data-testid={`editing-track-clip-${index}`}
                    className="editing-timeline-clip"
                    title={`${editingClipLabel(clip, index)} · ${timelineTime(items[index].startMs)} · ${Number(clip.duration_seconds).toFixed(3)} s`}
                    aria-pressed={selectedIndex === index}
                    draggable={false}
                    onDragStart={(event) => event.preventDefault()}
                    onPointerDown={(event) => reorderGesture.begin(event, index)}
                    onPointerMove={reorderGesture.move}
                    onPointerUp={reorderGesture.finish}
                    onPointerCancel={reorderGesture.cancel}
                    onLostPointerCapture={reorderGesture.cancel}
                    onClick={(event) => {
                      if (event.detail > 0 && reorderGesture.shouldSuppressClick()) return;
                      onSelectClip(index);
                    }}
                    onKeyDown={(event) => {
                      if (
                        event.altKey &&
                        (event.key === "ArrowLeft" || event.key === "ArrowRight")
                      ) {
                        event.preventDefault();
                        reorder(index, index + (event.key === "ArrowLeft" ? -1 : 1));
                      }
                    }}
                  >
                    <EditingClipThumbnail
                      projectId={projectId}
                      artifactId={typeof clip.artifact_id === "string" ? clip.artifact_id : null}
                      label={editingClipLabel(clip, index)}
                    />
                    <span className="editing-track-clip-label">
                      {editingClipLabel(clip, index)}
                    </span>
                    <small>{(items[index].durationMs / 1000).toFixed(2)} s</small>
                    {items[index].overlapMs > 0 && (
                      <small>淡化 {(items[index].overlapMs / 1000).toFixed(3)} s</small>
                    )}
                  </button>
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
              {reorderGesture.view && (
                <div
                  className="editing-drop-indicator"
                  data-testid="editing-drop-indicator"
                  style={{ left: reorderGesture.view.marker }}
                  aria-hidden="true"
                />
              )}
            </div>
          </nav>
          {(["audio", "subtitles"] as const).map((lane) => (
            <div
              key={lane}
              className="editing-timeline-lane"
              aria-label={copy[lane]}
              data-testid={`editing-${lane}-track`}
            >
              <strong>
                {lane === "audio" ? (
                  <Mic size={16} aria-hidden="true" />
                ) : (
                  <Type size={16} aria-hidden="true" />
                )}
                {copy[lane]}
              </strong>
              <div className="editing-track-body" style={{ width: pixels(total) }}>
                {clips.map((clip, index) => (
                  <button
                    type="button"
                    key={String(clip.id ?? index)}
                    className="editing-timeline-clip editing-timeline-cell"
                    data-lane={lane}
                    data-dragging={reorderGesture.view?.from === index}
                    style={{
                      left: pixels(items[index].startMs),
                      width: pixels(items[index].durationMs),
                      transform: reorderGesture.offset(index),
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
                  </button>
                ))}
              </div>
            </div>
          ))}
          {geometry.valid && (
            <div
              className="editing-timeline-cursor"
              data-testid="editing-timeline-cursor"
              aria-hidden="true"
              style={{
                left: `calc(var(--df-timeline-label-width) + var(--df-space-1) + ${pixels(Math.min(total, playheadMs))})`,
              }}
            >
              <span />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
