import type { ProjectSnapshot } from "./api";

export type ProjectArtifact = ProjectSnapshot["artifacts"][number];

const IMAGE_STORAGE_STATES = new Set(["available", "ready"]);

export function imageArtifacts(artifacts: ProjectArtifact[]): ProjectArtifact[] {
  return artifacts.filter(
    (artifact) =>
      artifact.mime_type.startsWith("image/") &&
      IMAGE_STORAGE_STATES.has(artifact.storage_state),
  );
}

export function latestImageArtifact(
  artifacts: ProjectArtifact[],
): ProjectArtifact | null {
  return imageArtifacts(artifacts)[0] ?? null;
}

export function shotKeyframeArtifact(
  snapshot: ProjectSnapshot,
  shotId: string,
): ProjectArtifact | null {
  const images = imageArtifacts(snapshot.artifacts);
  const run = snapshot.node_runs.find((candidate) => {
    const input = candidate.input_snapshot ?? {};
    const summary = candidate.output_summary ?? {};
    const runShotId = String(input.shot_id ?? "");
    const nodeKey = String(
      input.node_key ??
        summary.node_key ??
        summary.node_type ??
        summary.node_name ??
        "",
    );
    return runShotId === shotId && nodeKey === "keyframe";
  });
  if (!run) return null;

  return (
    images.find((artifact) => artifact.id === run.result_artifact_id) ??
    images.find((artifact) => artifact.produced_by_run_id === run.id) ??
    null
  );
}
