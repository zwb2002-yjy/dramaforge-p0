/**
 * MediaReviewCanvas (P6-02 / 03 §54).
 *
 * Image review overlay using normalized coordinates (0..1). Supports adding a
 * rectangular region or a point annotation. Pure presentational + callbacks.
 */

import { useRef } from "react";

export interface NormalizedRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MediaReviewCanvasProps {
  imageUrl: string;
  regions: NormalizedRegion[];
  onAddRegion?: (region: NormalizedRegion) => void;
  onAddPoint?: (x: number, y: number) => void;
  mode?: "region" | "point" | "view";
}

export function MediaReviewCanvas({
  imageUrl,
  regions,
  onAddRegion,
  onAddPoint,
  mode = "view",
}: MediaReviewCanvasProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  const toNormalized = (clientX: number, clientY: number) => {
    const rect = boxRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    const round = (value: number) => Math.round(value * 10000) / 10000;
    return {
      x: round(Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))),
      y: round(Math.min(1, Math.max(0, (clientY - rect.top) / rect.height))),
    };
  };

  const onMouseDown = (event: React.MouseEvent) => {
    if (mode === "view") return;
    const point = toNormalized(event.clientX, event.clientY);
    if (!point) return;
    if (mode === "point") {
      onAddPoint?.(point.x, point.y);
      return;
    }
    dragRef.current = point;
  };

  const onMouseUp = (event: React.MouseEvent) => {
    if (mode !== "region" || !dragRef.current) return;
    const point = toNormalized(event.clientX, event.clientY);
    if (!point) return;
    const start = dragRef.current;
    dragRef.current = null;
    onAddRegion?.({
      x: Math.min(start.x, point.x),
      y: Math.min(start.y, point.y),
      width: Math.round(Math.abs(point.x - start.x) * 10000) / 10000,
      height: Math.round(Math.abs(point.y - start.y) * 10000) / 10000,
    });
  };

  return (
    <div
      ref={boxRef}
      data-testid="media-review-canvas"
      className="relative inline-block cursor-crosshair overflow-hidden"
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
    >
      <img src={imageUrl} alt="review target" className="block max-w-full" />
      {regions.map((region, index) => (
        <div
          key={`${region.x}-${region.y}-${index}`}
          data-testid="review-region"
          className="absolute border-2 border-amber-500"
          style={{
            left: `${region.x * 100}%`,
            top: `${region.y * 100}%`,
            width: `${region.width * 100}%`,
            height: `${region.height * 100}%`,
          }}
        />
      ))}
    </div>
  );
}
