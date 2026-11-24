import type { EditableClip } from "./useTimelineDraft";
import { projectPublicContentUrl } from "../../lib/api";

type PublicSource = {
  kind: "public_material";
  publication_id: string;
  publication_item_id: string;
  public_asset_link_id: string;
};
export type PublicCutSelection = {
  action: "append" | "replace" | "audio";
  source: PublicSource;
  seconds: number;
  resetCrop: boolean;
};

export function publicCutUrl(
  projectId: string,
  clip: EditableClip | undefined,
  field: "source" | "audio_source",
) {
  const raw = clip?.[field];
  const source = raw as Partial<PublicSource> | null | undefined;
  if (
    !source ||
    typeof source !== "object" ||
    Array.isArray(source) ||
    source.kind !== "public_material" ||
    typeof source.public_asset_link_id !== "string" ||
    typeof source.publication_item_id !== "string"
  )
    return undefined;
  return projectPublicContentUrl(
    projectId,
    source.public_asset_link_id,
    source.publication_item_id,
  );
}

/** Resolve a shot's saved identity; a public or adopted-asset clip has no substitute Shot. */
export function formalClipSource(clip?: EditableClip) {
  if (!clip) return undefined;
  const raw=clip.source;
  if (typeof raw === "object" && raw !== null && !Array.isArray(raw)) {
    if (raw.kind !== "shot_formal" || typeof raw.shot_id !== "string" || typeof raw.artifact_id !== "string") return undefined;
    return {shotId:raw.shot_id, artifactId:raw.artifact_id, typed:true};
  }
  if (typeof clip.shot_id === "string" && typeof clip.artifact_id === "string")
    return {shotId:clip.shot_id, artifactId:clip.artifact_id, typed:false};
  return undefined;
}

export function localClipVideo(clip?: EditableClip): string | null {
  const shot=formalClipSource(clip);
  if (shot) return shot.artifactId;
  if (!clip?.source && typeof clip?.artifact_id === "string") return clip.artifact_id;
  const source=clip?.source, observed=clip?.selection_snapshot;
  if (source && typeof source==="object" && !Array.isArray(source) && source.kind==="asset_version"
      && observed && typeof observed==="object" && !Array.isArray(observed) && typeof observed.artifact_id==="string")
    return observed.artifact_id;
  return null;
}
