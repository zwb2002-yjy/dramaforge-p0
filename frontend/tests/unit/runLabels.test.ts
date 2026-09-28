import { describe, expect, it } from "vitest";

import { nodeRunStatusLabel } from "../../src/lib/runLabels";

describe("nodeRunStatusLabel", () => {
  it("uses one product vocabulary for every stored run status", () => {
    expect(nodeRunStatusLabel("queued")).toBe("已排队");
    expect(nodeRunStatusLabel("running")).toBe("执行中");
    expect(nodeRunStatusLabel("completed")).toBe("已完成");
    expect(nodeRunStatusLabel("cached")).toBe("已复用");
    expect(nodeRunStatusLabel("failed")).toBe("失败");
    expect(nodeRunStatusLabel("cancelled")).toBe("已取消");
    expect(nodeRunStatusLabel("cancel_requested")).toBe("取消中");
  });

  it("never prints a raw token for an unmapped status", () => {
    expect(nodeRunStatusLabel("provider_waiting")).toBe("状态待同步");
    expect(nodeRunStatusLabel(null)).toBe("—");
  });
});
