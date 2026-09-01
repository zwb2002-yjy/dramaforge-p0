import type { FormalKeyframeRead, FormalVideoRead, ShotLite } from "./api";
import { ShotCandidateTray } from "./ShotCandidateTray";

type ShotFormalOutputActionsProps = {
  projectId: string;
  shot: ShotLite;
  candidates: unknown[];
  onConfirmed?: (result: FormalKeyframeRead | FormalVideoRead) => void | Promise<void>;
};

/**
 * Compatibility export for legacy embedders.
 *
 * Formal confirmation now lives in ShotCandidateTray below the Scene canvas;
 * keeping this thin adapter avoids a second mutation implementation while
 * older imports migrate to the stage-first workbench.
 */
export function ShotFormalOutputActions({
  projectId,
  shot,
  candidates,
  onConfirmed,
}: ShotFormalOutputActionsProps) {
  return (
    <ShotCandidateTray
      projectId={projectId}
      shot={shot}
      candidates={candidates}
      onPreviewCandidate={() => undefined}
      onConfirmed={onConfirmed}
    />
  );
}
