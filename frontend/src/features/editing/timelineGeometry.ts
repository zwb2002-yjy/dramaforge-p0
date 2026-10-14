import type { EditableClip } from "./useTimelineDraft";
import type { TimelinePreviewRead } from "./api";
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Draft-only geometry. A current compiler plan supplies the authoritative time map. */
export function timelineGeometry(clips: EditableClip[], plan?: TimelinePreviewRead | null) {
  let end = 0;
  let valid = true;
  const items = clips.map((clip, index) => {
    const duration = Math.round(Number(clip.duration_seconds) * 1000);
    if (!Number.isFinite(duration) || duration < 1) valid = false;
    const durationMs = Number.isFinite(duration) && duration > 0 ? duration : 0;
    const transition = clip.transition;
    const kind =
      typeof transition === "string"
        ? transition
        : isObject(transition)
          ? String(transition.kind ?? transition.type ?? "cut")
          : "cut";
    const normalizedKind = kind.trim().toLowerCase();
    const rawOverlap =
      normalizedKind === "crossfade" && index > 0 && isObject(transition)
        ? Number(transition.duration_seconds ?? 0.25)
        : normalizedKind === "crossfade" && index > 0
          ? 0.25
          : 0;
    const overlap = Math.round(rawOverlap * 1000);
    const previousDuration =
      index > 0 ? Math.round(Number(clips[index - 1].duration_seconds) * 1000) : 0;
    if (
      !["cut", "crossfade"].includes(normalizedKind) ||
      (transition !== null &&
        transition !== undefined &&
        typeof transition !== "string" &&
        (typeof transition !== "object" || Array.isArray(transition))) ||
      !Number.isFinite(overlap) ||
      overlap < 0 ||
      (normalizedKind === "crossfade" &&
        index > 0 &&
        (overlap < 1 || overlap >= Math.min(durationMs, previousDuration)))
    )
      valid = false;
    const overlapMs =
      Number.isFinite(overlap) && overlap >= 0 && overlap < Math.min(durationMs, previousDuration)
        ? overlap
        : 0;
    const compiled = plan?.clips.find((item) => item.clip_id === clip.id);
    const startMs = compiled?.start_ms ?? end - overlapMs;
    end = compiled?.end_ms ?? startMs + durationMs;
    return { startMs, endMs: end, durationMs: compiled?.duration_ms ?? durationMs, overlapMs };
  });
  return { items, durationMs: plan?.duration_ms ?? end, valid, compiled: !!plan };
}

/** Crop within the current source interval, preserving its speed; never edits provenance. */
export function cropClip(
  clip: EditableClip,
  edge: "in" | "out",
  seconds: number,
): EditableClip | null {
  const duration = Math.round(Number(clip.duration_seconds) * 1000);
  const sourceIn = Math.round(Number(clip.source_in_seconds ?? 0) * 1000);
  const sourceOut =
    clip.source_out_seconds === null || clip.source_out_seconds === undefined
      ? sourceIn + duration
      : Math.round(Number(clip.source_out_seconds) * 1000);
  if (
    ![duration, sourceIn, sourceOut, seconds].every(Number.isFinite) ||
    duration < 2 ||
    sourceIn < 0 ||
    sourceOut <= sourceIn
  )
    return null;
  const amount = Math.min(
    duration - 1,
    Math.floor(((sourceOut - sourceIn - 1) * duration) / (sourceOut - sourceIn)),
    Math.max(0, Math.round(seconds * 1000)),
  );
  if (!amount) return null;
  const sourceDelta = Math.round((amount * (sourceOut - sourceIn)) / duration);
  const nextIn = edge === "in" ? sourceIn + sourceDelta : sourceIn;
  const nextOut = edge === "out" ? sourceOut - sourceDelta : sourceOut;
  if (nextOut <= nextIn) return null;
  return {
    ...clip,
    source_in_seconds: nextIn / 1000,
    source_out_seconds: nextOut / 1000,
    duration_seconds: (duration - amount) / 1000,
  };
}
