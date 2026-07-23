import { artifactContentUrl, type ProjectSnapshot } from "./api";
import type { ProjectArtifact } from "./projectMedia";

export function useStageArtifact(
  projectId: string,
  arts: ProjectArtifact[],
  selectedShotId: string | null,
  snapshot: ProjectSnapshot | null | undefined,
) {
  const latestArt = arts[0] ?? null;
  const selectedShotArt =
    selectedShotId && snapshot
      ? snapshot.artifacts.find(
          (a) =>
            a.mime_type.startsWith("image/") &&
            a.produced_by_run_id &&
            snapshot.node_runs.some(
              (r) =>
                r.id === a.produced_by_run_id &&
                String(r.input_snapshot?.shot_id ?? "") === selectedShotId,
            ),
        ) ?? null
      : null;
  const stageArt = selectedShotId ? selectedShotArt : latestArt;
  const stageUrl =
    stageArt && projectId !== "demo" ? artifactContentUrl(projectId, stageArt.id) : null;
  return { latestArt, selectedShotArt, stageArt, stageUrl };
}
