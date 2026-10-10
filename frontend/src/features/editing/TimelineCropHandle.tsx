import { useRef, useState } from "react";
import { Button } from "../../components/ui";
import type { EditableClip } from "./useTimelineDraft";
import { cropClip } from "./timelineGeometry";
import { timelineCopy as copy } from "./timelineCopy";

export function TimelineCropHandle({
  clip,
  index,
  edge,
  onCrop,
}: {
  clip: EditableClip;
  index: number;
  edge: "in" | "out";
  onCrop: (clip: EditableClip) => void;
}) {
  const gesture = useRef<{
    x: number;
    pixelsPerSecond: number;
    clip: EditableClip;
    pointer: number;
  } | null>(null);
  const suppressClick = useRef(false);
  const [pending, setPending] = useState<EditableClip | null>(null);
  const update = (x: number) => {
    const start = gesture.current;
    if (!start || start.clip !== clip) return null;
    return cropClip(
      start.clip,
      edge,
      ((x - start.x) / start.pixelsPerSecond) * (edge === "in" ? 1 : -1),
    );
  };
  return (
    <Button
      className={`editing-crop-handle editing-crop-${edge}`}
      data-testid={`editing-crop-${edge}-${index}`}
      aria-label={`${copy.crop[edge]} · ${copy.clip} ${index + 1}`}
      title={`${copy.crop[edge]} · ${copy.cropHint}`}
      disabled={Number(clip.duration_seconds) <= 0.001}
      onClick={() => {
        if (suppressClick.current) {
          suppressClick.current = false;
          return;
        }
        const cropped = cropClip(clip, edge, 0.1);
        if (cropped) onCrop(cropped);
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        const width = event.currentTarget.parentElement?.getBoundingClientRect().width ?? 0;
        if (!width || !(Number(clip.duration_seconds) > 0)) return;
        gesture.current = {
          x: event.clientX,
          pixelsPerSecond: width / Number(clip.duration_seconds),
          clip,
          pointer: event.pointerId,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
        setPending(null);
        suppressClick.current = false;
      }}
      onPointerMove={(event) => {
        if (gesture.current?.pointer !== event.pointerId) return;
        setPending(update(event.clientX));
      }}
      onPointerUp={(event) => {
        if (gesture.current?.pointer !== event.pointerId) return;
        const moved = Math.abs(event.clientX - gesture.current.x) > 2;
        const cropped = update(event.clientX);
        gesture.current = null;
        setPending(null);
        suppressClick.current = moved;
        if (moved && cropped) onCrop(cropped);
      }}
      onLostPointerCapture={() => {
        gesture.current = null;
        setPending(null);
      }}
      onPointerCancel={() => {
        gesture.current = null;
        suppressClick.current = true;
        setPending(null);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && gesture.current) {
          event.preventDefault();
          gesture.current = null;
          suppressClick.current = true;
          setPending(null);
        }
      }}
    >
      <span aria-hidden="true">{edge === "in" ? "[" : "]"}</span>
      {pending && (
        <output className="editing-crop-value" role="status">
          {Number(pending.duration_seconds).toFixed(3)} s
        </output>
      )}
    </Button>
  );
}
