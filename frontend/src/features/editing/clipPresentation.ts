import type { EditableClip } from "./useTimelineDraft";
import { timelineCopy as copy } from "./timelineCopy";

/** Use the session's frozen source labels, so reordering never renumbers a shot. */
export function editingClipLabel(clip: EditableClip, index: number): string {
  const shot = Number(clip.shot_number);
  const scene = Number(clip.scene_number);
  if (!Number.isInteger(shot) || shot < 1) return `${copy.clip} ${index + 1}`;
  return Number.isInteger(scene) && scene > 0
    ? `${copy.scene} ${scene} · ${copy.shot} ${shot}`
    : `${copy.shot} ${shot}`;
}

export function timelineTime(milliseconds: number): string {
  const value = Math.max(0, Math.round(milliseconds));
  const minutes = Math.floor(value / 60000);
  const seconds = Math.floor((value % 60000) / 1000);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(value % 1000).padStart(3, "0")}`;
}
