import { describe, expect, it } from "vitest";

import { shouldInitializeConceptChoices } from "../../src/features/director/CreativeStage";

describe("shouldInitializeConceptChoices", () => {
  it("seeds fields when the creator selects a new concept", () => {
    expect(shouldInitializeConceptChoices("concept-b", "concept-a")).toBe(true);
    expect(shouldInitializeConceptChoices("concept-a", null)).toBe(true);
  });

  it("preserves the current story core when restoring its selected concept", () => {
    expect(shouldInitializeConceptChoices("concept-a", "concept-a")).toBe(false);
  });

  it("does nothing without a selected concept", () => {
    expect(shouldInitializeConceptChoices(null, "concept-a")).toBe(false);
  });
});
