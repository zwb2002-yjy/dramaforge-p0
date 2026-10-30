import { describe, expect, it } from "vitest";

import { assetKindLabel, assetStatusLabel } from "../../src/lib/assetLabels";
import { slotLabel } from "../../src/lib/modelProfile";
import { nodeRunStatusLabel } from "../../src/lib/runLabels";
import { timeOfDayLabel } from "../../src/lib/sceneLabels";
import { zhErrorParts, zhEvidenceState } from "../../src/lib/zh";

/**
 * One invariant for every shared vocabulary module: a stored contract value the
 * UI does not recognise must not be printed on an ordinary surface. Creator
 * written Chinese still passes through, because that is content, not a token.
 */
describe("shared vocabulary fallbacks", () => {
  it("keeps the known values in Chinese", () => {
    expect(assetKindLabel("character")).toBe("角色");
    expect(assetStatusLabel("recycled")).toBe("已回收");
    expect(slotLabel("visual.keyframe")).toBe("镜头关键帧");
    expect(nodeRunStatusLabel("completed")).toBe("已完成");
    expect(timeOfDayLabel("day")).toBe("白天");
    expect(zhEvidenceState("quality_gated")).toBe("已质量门禁");
  });

  it("replaces an unknown stored token with product wording", () => {
    expect(assetKindLabel("hologram")).toBe("其他类型");
    expect(assetStatusLabel("archived")).toBe("状态待同步");
    expect(slotLabel("visual.new_slot")).toBe("其他环节");
    expect(nodeRunStatusLabel("provider_waiting")).toBe("状态待同步");
    expect(timeOfDayLabel("golden_hour_v2")).toBe("时段待确认");
    expect(zhEvidenceState("cost_verified")).toBe("状态待确认");
  });

  it("passes creator written Chinese through instead of hiding it", () => {
    expect(assetKindLabel("主角特写")).toBe("主角特写");
    expect(timeOfDayLabel("黄昏后")).toBe("黄昏后");
  });

  it("keeps the stored value available for diagnostics", () => {
    const parts = zhErrorParts(
      "WORKER_ERROR",
      "selected model binding is not eligible for this intent",
    );
    expect(parts.label).toBe("执行失败");
    expect(parts.raw).toBe("selected model binding is not eligible for this intent");
  });
});
