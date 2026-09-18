import { describe, expect, it } from "vitest";

import {
  capabilityGapReason,
  capabilityGapSeverityLabel,
  executionModelLabel,
  referenceDeliveryLabel,
} from "../../src/lib/executionPlanLabels";

describe("executionPlanLabels", () => {
  it("states reference adaptation in creative language", () => {
    expect(referenceDeliveryLabel("exact")).toBe("完全支持");
    expect(referenceDeliveryLabel("approximate")).toBe("近似支持");
    expect(referenceDeliveryLabel("unsupported")).toBe("不支持");
    // An unknown contract value must not reach the surface as a raw token.
    expect(referenceDeliveryLabel("brand_new_state")).toBe("适配情况待确认");
    expect(referenceDeliveryLabel(null)).toBe("—");
  });

  it("states gap severity in creative language", () => {
    expect(capabilityGapSeverityLabel("fatal")).toBe("无法执行");
    expect(capabilityGapSeverityLabel("warning")).toBe("需要注意");
    expect(capabilityGapSeverityLabel("新状态")).toBe("需要注意");
  });

  it("translates the known capability-gap sentences and keeps unknown ones for diagnostics", () => {
    expect(
      capabilityGapReason("model does not declare input slot for this reference role"),
    ).toEqual({ label: "该模型没有声明对应的输入位", raw: null });
    expect(capabilityGapReason("reference count exceeds the declared input slot maximum")).toEqual({
      label: "参考数量超过该模型允许的上限",
      raw: null,
    });
    const unknown = capabilityGapReason("some new provider specific sentence");
    expect(unknown.label).toBe("该模型无法满足本次参考素材要求");
    expect(unknown.raw).toBe("some new provider specific sentence");
  });

  it("resolves a model display name from the catalogue and never prints the raw id", () => {
    const catalog = [{ id: "agnes/agnes-image-2.1-flash", display_name: "Agnes Image Flash" }];
    expect(executionModelLabel("agnes/agnes-image-2.1-flash", catalog)).toEqual({
      label: "Agnes Image Flash",
      raw: "agnes/agnes-image-2.1-flash",
    });
    expect(executionModelLabel("agnes/not-in-catalog", catalog).label).toBe("已解析执行模型");
    expect(executionModelLabel("", catalog).label).toBe("尚未解析执行模型");
  });
});
