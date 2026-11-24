import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchProductionSummary,
  productionReadErrorMessage,
} from "../../src/features/production/api";

const summary = {
  project_id: "p1",
  total_runs: 0,
  completed_runs: 0,
  running_runs: 0,
  failed_runs: 0,
  artifact_count: 0,
  recent_failures: [],
  has_more_failures: false,
  stages: [{ node_key: "video", status_counts: {}, latest_failure: null }],
};
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => vi.restoreAllMocks());

describe("Production stage read contract", () => {
  it.each([
    [null],
    ["video"],
    [{}],
    [{ node_key: "video", status_counts: null, latest_failure: null }],
    [{ node_key: "video", status_counts: [], latest_failure: null }],
    [{ node_key: "video", status_counts: { failed: -1 }, latest_failure: null }],
    [{ node_key: "video", status_counts: { completed: 0.5 }, latest_failure: null }],
    [{ node_key: "video", status_counts: { completed: "1" }, latest_failure: null }],
    [{ node_key: "video", status_counts: {}, latest_failure: { node_key: "keyframe" } }],
    [{ node_key: "video", status_counts: {} }],
  ])("rejects malformed stage %j with a contract error", async (stage) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ ...summary, stages: [stage] }));
    await expect(fetchProductionSummary("p1")).rejects.toThrow("制作摘要回执不完整");
  });

  it("rejects duplicate stage identities", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({
        ...summary,
        stages: [...summary.stages, ...summary.stages],
      }),
    );
    await expect(fetchProductionSummary("p1")).rejects.toThrow("制作摘要回执不完整");
  });

  it("preserves empty counts and positive counts without implying approval", async () => {
    const value = {
      ...summary,
      stages: [
        ...summary.stages,
        { node_key: "keyframe", status_counts: { completed: 2 }, latest_failure: null },
      ],
    };
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(json(value));
    await expect(fetchProductionSummary("p1")).resolves.toEqual(value);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("explains the unavailable read without suggesting a regeneration", () => {
    expect(productionReadErrorMessage(new Error("failed"))).toContain("未知状态");
  });
});
