import { useCallback, useEffect, useRef, useState, type PointerEvent, type RefObject } from "react";
import type { EditableClip } from "./useTimelineDraft";

type DragView = { from: number; to: number; offset: number; marker: number; width: number };
type Gesture = {
  pointer: number;
  from: number;
  x: number;
  y: number;
  clientX: number;
  clientY: number;
  scroll: number;
  maxScroll: number;
  active: boolean;
  signature: string;
  element: HTMLButtonElement;
  body: HTMLElement;
  cells: { index: number; left: number; width: number; center: number }[];
};

/** Pointer capture owns one gesture; only release commits a linked clip reorder. */
export function useTimelineReorder({
  clips,
  scroller,
  onSelect,
  onReorder,
  onInteractionStart,
}: {
  clips: EditableClip[];
  scroller: RefObject<HTMLDivElement>;
  onSelect: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onInteractionStart?: () => void;
}) {
  const [view, setView] = useState<DragView | null>(null);
  const gesture = useRef<Gesture | null>(null);
  const frame = useRef(0);
  const suppressClick = useRef(false);
  const current = useRef({ signature: JSON.stringify(clips), onSelect, onReorder });
  current.current = { signature: JSON.stringify(clips), onSelect, onReorder };
  const cancel = useCallback(() => {
    const before = gesture.current;
    gesture.current = null;
    cancelAnimationFrame(frame.current);
    setView(null);
    if (before?.element.hasPointerCapture(before.pointer))
      before.element.releasePointerCapture(before.pointer);
  }, []);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && gesture.current) {
        event.preventDefault();
        suppressClick.current = true;
        cancel();
      }
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      cancelAnimationFrame(frame.current);
    };
  }, [cancel]);
  function project(start: Gesture): DragView | null {
    const container = scroller.current;
    if (!container || current.current.signature !== start.signature) return null;
    const bounds = container.getBoundingClientRect();
    if (start.clientY < bounds.top || start.clientY > bounds.bottom) return null;
    const localX = start.clientX - start.body.getBoundingClientRect().left;
    const remaining = start.cells.filter((cell) => cell.index !== start.from);
    const movingLeft = start.clientX < start.x;
    const found = remaining.findIndex((cell) =>
      movingLeft ? localX <= cell.center + 0.5 : localX < cell.center - 0.5,
    );
    const to = found < 0 ? remaining.length : found;
    const origin = start.cells[start.from];
    const marker =
      to === start.from
        ? origin.left
        : to > start.from
          ? start.cells[to].left + start.cells[to].width - origin.width
          : start.cells[to].left;
    return {
      from: start.from,
      to,
      marker,
      width: origin.width,
      offset: start.clientX - start.x + container.scrollLeft - start.scroll,
    };
  }
  function autoScroll() {
    const start = gesture.current;
    const container = scroller.current;
    if (!start?.active || !container) return;
    const bounds = container.getBoundingClientRect();
    const edge = 40;
    const delta =
      start.clientX > bounds.right - edge
        ? Math.min(18, (start.clientX - bounds.right + edge) / 2)
        : start.clientX < bounds.left + edge
          ? -Math.min(18, (bounds.left + edge - start.clientX) / 2)
          : 0;
    const next = Math.max(0, Math.min(start.maxScroll, container.scrollLeft + delta));
    if (next !== container.scrollLeft) {
      container.scrollLeft = next;
      setView(project(start));
    }
    frame.current = requestAnimationFrame(autoScroll);
  }
  function begin(event: PointerEvent<HTMLButtonElement>, index: number) {
    if (event.button !== 0 || clips.length < 2) return;
    const container = scroller.current;
    const body = event.currentTarget.parentElement?.parentElement;
    if (!container || !body) return;
    // Playback can change URL selection at a cut and interrupt pointer capture.
    onInteractionStart?.();
    event.preventDefault();
    suppressClick.current = false;
    event.currentTarget.focus({ preventScroll: true });
    const bodyBounds = body.getBoundingClientRect();
    const cells = [...body.querySelectorAll<HTMLElement>("[data-editing-index]")].map((cell) => {
      const bounds = cell.getBoundingClientRect();
      const target =
        cell.querySelector(".editing-timeline-clip")?.getBoundingClientRect() ?? bounds;
      return {
        index: Number(cell.dataset.editingIndex),
        left: bounds.left - bodyBounds.left,
        width: bounds.width,
        center: target.left - bodyBounds.left + target.width / 2,
      };
    });
    gesture.current = {
      pointer: event.pointerId,
      from: index,
      x: event.clientX,
      y: event.clientY,
      clientX: event.clientX,
      clientY: event.clientY,
      scroll: container.scrollLeft,
      maxScroll: Math.max(0, container.scrollWidth - container.clientWidth),
      active: false,
      signature: current.current.signature,
      element: event.currentTarget,
      body,
      cells,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<HTMLButtonElement>) {
    const start = gesture.current;
    if (!start || start.pointer !== event.pointerId) return;
    start.clientX = event.clientX;
    start.clientY = event.clientY;
    if (!start.active) {
      if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4) return;
      start.active = true;
      suppressClick.current = true;
      frame.current = requestAnimationFrame(autoScroll);
    }
    setView(project(start));
  }
  function finish(event: PointerEvent<HTMLButtonElement>) {
    const start = gesture.current;
    if (!start || start.pointer !== event.pointerId) return;
    start.clientX = event.clientX;
    start.clientY = event.clientY;
    const result = start.active ? project(start) : null;
    cancel();
    // Updating URL selection during pointer capture can cancel the browser gesture.
    // Select the source identity only when committing the completed move.
    if (result && result.from !== result.to) {
      current.current.onSelect(result.from);
      current.current.onReorder(result.from, result.to);
    }
  }
  function offset(index: number) {
    if (!view) return undefined;
    const x =
      index === view.from
        ? view.offset
        : view.from < index && index <= view.to
          ? -view.width
          : view.to <= index && index < view.from
            ? view.width
            : 0;
    return x ? `translateX(${x}px)` : undefined;
  }
  return {
    view,
    begin,
    move,
    finish,
    cancel,
    offset,
    shouldSuppressClick: () => {
      const result = suppressClick.current;
      suppressClick.current = false;
      return result;
    },
  };
}
