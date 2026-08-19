import { describe, expect, it } from "vitest";

import type { ProjectSnapshot } from "../../src/lib/api";
import {
  imageArtifacts,
  latestImageArtifact,
  shotKeyframeArtifact,
} from "../../src/lib/projectMedia";

const snapshot: ProjectSnapshot = {
  project_id: "project-1",
  name: "Preview mapping",
  node_runs: [
    {
      id: "run-json",
      status: "completed",
      result_artifact_id: "artifact-json",
      output_summary: { node_type: "identity_review" },
      input_snapshot: { shot_id: "shot-1", node_key: "identity_review" },
      idempotency_key: "identity_review:shot-1",
      attempt_no: 1,
      node_key: "identity_review",
      provider_cost: "0",
      started_at: null,
      finished_at: null,
      error_code: null,
      error_summary: null,
      upstream_dependencies: [],
    },
    {
      id: "run-shot-2",
      status: "completed",
      result_artifact_id: "artifact-shot-2",
      output_summary: { node_type: "keyframe" },
      input_snapshot: { shot_id: "shot-2", node_key: "keyframe" },
      idempotency_key: "keyframe:shot-2",
      attempt_no: 1,
      node_key: "keyframe",
      provider_cost: "0",
      started_at: null,
      finished_at: null,
      error_code: null,
      error_summary: null,
      upstream_dependencies: [],
    },
    {
      id: "run-shot-1",
      status: "completed",
      result_artifact_id: "artifact-shot-1",
      output_summary: { node_type: "keyframe" },
      input_snapshot: { shot_id: "shot-1", node_key: "keyframe" },
      idempotency_key: "keyframe:shot-1",
      attempt_no: 1,
      node_key: "keyframe",
      provider_cost: "0",
      started_at: null,
      finished_at: null,
      error_code: null,
      error_summary: null,
      upstream_dependencies: [],
    },
  ],
  artifacts: [
    {
      id: "artifact-json",
      object_key: "projects/project-1/identity_review/run.json",
      content_hash: "json",
      byte_size: 232,
      mime_type: "application/json",
      storage_state: "ready",
      produced_by_run_id: "run-json",
      width: null,
      height: null,
      duration_seconds: null,
    },
    {
      id: "artifact-shot-2",
      object_key: "projects/project-1/keyframe/shot-2.png",
      content_hash: "shot-2",
      byte_size: 2048,
      mime_type: "image/png",
      storage_state: "ready",
      produced_by_run_id: "run-shot-2",
      width: 736,
      height: 1312,
      duration_seconds: null,
    },
    {
      id: "artifact-shot-1",
      object_key: "projects/project-1/keyframe/shot-1.png",
      content_hash: "shot-1",
      byte_size: 2048,
      mime_type: "image/png",
      storage_state: "ready",
      produced_by_run_id: "run-shot-1",
      width: 736,
      height: 1312,
      duration_seconds: null,
    },
    {
      id: "artifact-video",
      object_key: "projects/project-1/video/shot-1.mp4",
      content_hash: "video",
      byte_size: 4096,
      mime_type: "video/mp4",
      storage_state: "ready",
      produced_by_run_id: null,
      width: 720,
      height: 1280,
      duration_seconds: "5.042",
    },
  ],
  provider_operations: [],
};

describe("project media selection", () => {
  it("never selects JSON or video artifacts for image elements", () => {
    expect(imageArtifacts(snapshot.artifacts).map((artifact) => artifact.id)).toEqual([
      "artifact-shot-2",
      "artifact-shot-1",
    ]);
    expect(latestImageArtifact(snapshot.artifacts)?.id).toBe("artifact-shot-2");
  });

  it("maps a Shot to the image produced by its own keyframe NodeRun", () => {
    expect(shotKeyframeArtifact(snapshot, "shot-1")?.id).toBe("artifact-shot-1");
    expect(shotKeyframeArtifact(snapshot, "shot-2")?.id).toBe("artifact-shot-2");
    expect(shotKeyframeArtifact(snapshot, "shot-3")).toBeNull();
  });
});
