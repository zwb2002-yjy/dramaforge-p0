import { describe, expect, it } from "vitest";

import {
  describeScriptImportOutcome,
  scriptTextSizeError,
  MAX_SCRIPT_TEXT_BYTES,
} from "../../src/features/script/api";

describe("script import client contract", () => {
  it("explains the 1 MiB bound in UTF-8 bytes", () => {
    expect(MAX_SCRIPT_TEXT_BYTES).toBe(1024 * 1024);
    expect(scriptTextSizeError("x".repeat(100))).toBeNull();
    const oversized = scriptTextSizeError("x".repeat(MAX_SCRIPT_TEXT_BYTES + 1));
    expect(oversized).toContain("1 MiB");
    // Multi-byte text is measured in bytes, not characters.
    expect(scriptTextSizeError("剧".repeat(MAX_SCRIPT_TEXT_BYTES / 3 + 1))).not.toBeNull();
  });

  it("separates a first import from a re-imported identical script", () => {
    const created = describeScriptImportOutcome({
      import_outcome: "created",
      scene_count: 2,
      shot_count: 3,
    });
    expect(created.tone).toBe("created");
    expect(created.message).toContain("新增 2 个场景 / 3 个镜头");

    const reused = describeScriptImportOutcome({
      import_outcome: "reused",
      scene_count: 2,
      shot_count: 3,
    });
    expect(reused.tone).toBe("reused");
    expect(reused.message).toContain("已存在");
    expect(reused.message).toContain("不会重复创建");
  });
});
