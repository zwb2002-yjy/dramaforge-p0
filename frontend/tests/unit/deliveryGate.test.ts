import { describe, expect, it } from "vitest";

import { ApiError } from "../../src/lib/api";
import { deliveryGateMessage } from "../../src/features/editing/deliveryGate";

describe("deliveryGateMessage", () => {
  it("explains a delivery blocked by a missing human decision", () => {
    const error = new ApiError(
      "a timeline clip has not been approved by a human review decision",
      422,
      "VALIDATION_ERROR",
      {
        code: "DELIVERY_REVIEW_REQUIRED",
        reason: "REVIEW_DECISION_MISSING",
      },
    );

    const message = deliveryGateMessage(error);

    expect(message).toContain("尚未记录人工决定");
    expect(message).toContain("待审内容");
  });

  it("distinguishes a machine request for a person from a stale decision", () => {
    const awaiting = deliveryGateMessage(
      new ApiError("blocked", 422, "VALIDATION_ERROR", {
        code: "DELIVERY_REVIEW_REQUIRED",
        reason: "REVIEW_AWAITING_HUMAN",
      }),
    );
    const stale = deliveryGateMessage(
      new ApiError("blocked", 422, "VALIDATION_ERROR", {
        code: "DELIVERY_REVIEW_REQUIRED",
        reason: "REVIEW_DECISION_STALE",
      }),
    );

    expect(awaiting).toContain("要求人工判断");
    expect(stale).toContain("不再适用");
    expect(awaiting).not.toBe(stale);
  });

  it("keeps the raw message for unrelated failures", () => {
    expect(deliveryGateMessage(new Error("network down"))).toBe("network down");
    expect(
      deliveryGateMessage(
        new ApiError("render failed", 422, "VALIDATION_ERROR", { code: "OTHER" }),
      ),
    ).toBe("render failed");
    expect(deliveryGateMessage("plain")).toBe("plain");
  });
});
