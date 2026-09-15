import { afterEach, describe, expect, it } from "vitest";

import {
  clearProductionOperation,
  productionOperationScope,
  readProductionOperation,
  recordProductionOperation,
} from "../../src/features/shots/productionOperationStore";

const OPERATION = {
  operationKey: "shot:shot-1:" + "a".repeat(64),
  planFingerprint: "a".repeat(64),
  stage: "image_keyframe" as const,
  recordedAt: "2026-09-15T00:00:00.000Z",
  nodeRunId: null,
};

describe("productionOperationStore", () => {
  afterEach(() => window.localStorage.clear());

  it("remembers one operation so a reload can adopt it", () => {
    const scope = productionOperationScope("workspace-1", "project-1", "shot-1", "image_keyframe");
    expect(readProductionOperation(scope)).toBeNull();

    recordProductionOperation(scope, OPERATION);
    expect(readProductionOperation(scope)).toEqual(OPERATION);

    clearProductionOperation(scope);
    expect(readProductionOperation(scope)).toBeNull();
  });

  it("isolates operations per workspace, project, shot and stage", () => {
    const scopes = [
      productionOperationScope("workspace-1", "project-1", "shot-1", "image_keyframe"),
      productionOperationScope("workspace-2", "project-1", "shot-1", "image_keyframe"),
      productionOperationScope("workspace-1", "project-2", "shot-1", "image_keyframe"),
      productionOperationScope("workspace-1", "project-1", "shot-2", "image_keyframe"),
      productionOperationScope("workspace-1", "project-1", "shot-1", "video"),
      productionOperationScope(null, "project-1", "shot-1", "image_keyframe"),
    ];
    expect(new Set(scopes).size).toBe(scopes.length);

    recordProductionOperation(scopes[0]!, OPERATION);
    expect(readProductionOperation(scopes[0]!)).toEqual(OPERATION);
    for (const other of scopes.slice(1)) {
      expect(readProductionOperation(other)).toBeNull();
    }
  });

  it("ignores unreadable or malformed storage instead of guessing an operation", () => {
    window.localStorage.setItem("dramaforge.production-operations", "{not json");
    expect(readProductionOperation("any")).toBeNull();

    window.localStorage.setItem(
      "dramaforge.production-operations",
      JSON.stringify({ any: { operationKey: "k", planFingerprint: "", stage: "unknown" } }),
    );
    expect(readProductionOperation("any")).toBeNull();
  });
});
