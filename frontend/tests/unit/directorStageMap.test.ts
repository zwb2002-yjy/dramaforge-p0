import { describe, expect, it } from "vitest";

import {
  DIRECTOR_STAGES,
  stageForStatus,
  stageState,
} from "../../src/features/director/stageMap";

describe("Director four-stage mapping", () => {
  it("keeps the four hard confirmations separate from runtime statuses", () => {
    expect(DIRECTOR_STAGES.map((stage) => stage.id)).toEqual([
      "creative",
      "shooting",
      "trial",
      "production",
    ]);
    expect(stageForStatus("awaiting_creative_confirmation")).toBe("creative");
    expect(stageForStatus("awaiting_production_authorization")).toBe("production");
    expect(stageForStatus("repair_proposed")).toBe("production");
    expect(stageForStatus("final_review")).toBe("production");
  });

  it("keeps terminal stop decisions visible in production and opens production only after acceptance", () => {
    expect(stageForStatus("cancelled")).toBe("production");
    expect(stageForStatus("awaiting_trial_review")).toBe("trial");
    expect(stageForStatus("awaiting_production_authorization")).toBe("production");
  });

  it("marks only upstream stages complete", () => {
    expect(stageState("creative", "trial", "awaiting_trial_authorization")).toBe("done");
    expect(stageState("shooting", "trial", "awaiting_trial_authorization")).toBe("done");
    expect(stageState("trial", "trial", "awaiting_trial_authorization")).toBe("active");
    expect(stageState("production", "trial", "awaiting_trial_authorization")).toBe("pending");
  });
});
