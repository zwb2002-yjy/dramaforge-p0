import { describe, expect, it } from "vitest";

import type { DirectorWorkspaceSnapshot } from "../../src/features/director/types";
import { shootingReadiness } from "../../src/features/director/types";

function artifact(kind: string, payload: Record<string, unknown>) {
  return { id: kind, project_id: "p", workflow_run_id: "w", artifact_kind: kind, revision_no: 1, supersedes_version_id: null, source_kind: "service", payload, content_hash: kind, status: "draft" };
}

function snapshot(selectionStatus: "ready" | "configuration_required") {
  return {
    current_artifacts: {
      storyboard_plan: artifact("storyboard_plan", { shots: [{}, {}, {}] }),
      risk_report: artifact("risk_report", { status: "ready" }),
      selection_plan: artifact("selection_plan", { status: selectionStatus }),
      cost_estimate: artifact("cost_estimate", {
        pricing_snapshot_id: "price",
        trial: [{ purpose: "video", status: "known" }],
        trial_total: "1.00",
      }),
    },
  } as unknown as DirectorWorkspaceSnapshot;
}

describe("shootingReadiness", () => {
  it("blocks hard confirmation while provider capability is not ready", () => {
    expect(shootingReadiness(snapshot("configuration_required"))).toEqual({
      ready: false,
      reasons: ["所需图片、视频或声音能力尚未配置并验证"],
    });
  });

  it("allows the shooting confirmation only when every deterministic precondition is ready", () => {
    expect(shootingReadiness(snapshot("ready"))).toEqual({ ready: true, reasons: [] });
  });

  it("blocks confirmation when a trial media price is unknown", () => {
    const value = snapshot("ready");
    value.current_artifacts.cost_estimate!.payload.trial = [
      { purpose: "video", status: "provider_not_reported" },
    ];
    value.current_artifacts.cost_estimate!.payload.trial_total = null;
    expect(shootingReadiness(value)).toEqual({
      ready: false,
      reasons: ["试拍价格尚未经过验证"],
    });
  });
});
