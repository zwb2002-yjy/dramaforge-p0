import { describe, expect, it } from "vitest";

import { ApiError } from "../../src/lib/api";
import {
  EXPERIMENT_STAGE_OPERATION,
  EXPERIMENT_STAGE_ORDER,
  experimentErrorDetail,
  experimentErrorMessage,
  experimentStageOf,
  modelIssueLabels,
} from "../../src/features/production/experimentStage";

describe("experimentStage", () => {
  it("keeps the stage vocabulary aligned with the model operations", () => {
    expect(EXPERIMENT_STAGE_ORDER).toEqual(["keyframe", "video"]);
    expect(EXPERIMENT_STAGE_OPERATION.keyframe).toBe("image.generate");
    expect(EXPERIMENT_STAGE_OPERATION.video).toBe("video.generate");
  });

  it("normalizes a stored target stage without inventing one", () => {
    expect(experimentStageOf("keyframe")).toBe("keyframe");
    expect(experimentStageOf("video")).toBe("video");
    // Experiments created before the stage was choosable persisted nothing;
    // "video" is the historical server default, so it stays the fallback.
    expect(experimentStageOf(undefined)).toBe("video");
    expect(experimentStageOf("nonsense")).toBe("video");
  });

  it("explains a missing binding for the stage that was actually requested", () => {
    const error = new ApiError(
      "selected experiment model has no enabled workspace binding",
      422,
      "VALIDATION_ERROR",
      {
        code: "MODEL_BINDING_MISSING",
        selected_model: "agnes/agnes-image-2.1-flash",
        purpose: "video",
      },
    );
    expect(experimentErrorMessage(error, "video")).toContain("视频阶段");
    expect(experimentErrorMessage(error, "keyframe")).toContain("关键帧阶段");
  });

  it("translates eligibility issue codes and never repeats them raw", () => {
    const error = new ApiError(
      "selected model binding is not eligible for this intent",
      422,
      "VALIDATION_ERROR",
      {
        code: "MODEL_INELIGIBLE",
        issues: ["MODEL_QUALITY_GATE_MISSING", "MODEL_NOT_ACCOUNT_VERIFIED"],
      },
    );
    const message = experimentErrorMessage(error, "keyframe");
    expect(message).toContain("尚未通过画质验收");
    expect(message).toContain("尚未完成账号验证");
    expect(message).not.toContain("MODEL_QUALITY_GATE_MISSING");
  });

  it("reports a committed-but-unqueued experiment as recoverable", () => {
    const error = new ApiError("QUEUE_UNAVAILABLE", 422, "VALIDATION_ERROR", {
      code: "QUEUE_UNAVAILABLE",
    });
    expect(experimentErrorMessage(error, "keyframe")).toContain("高级恢复");
  });

  it("falls back to product wording for unknown failures and keeps the raw detail apart", () => {
    expect(experimentErrorMessage(new Error("boom"), "video")).toBe(
      "实验请求未被接受，请确认镜头、阶段与模型后重试。",
    );
    expect(experimentErrorDetail(new Error("boom"))).toBe("boom");
    expect(modelIssueLabels(["SOMETHING_NEW"])).toBe("未通过资格检查");
  });
});
