import {
  createRootRoute,
  createRouter,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewWorkspace } from "../../src/features/review/ReviewWorkspace";
import {
  reviewTargetHref,
  reviewTargetSearch,
  type ReviewTargetSearch,
} from "../../src/features/review/reviewTarget";

const shot = {
  id: "s1",
  project_id: "p1",
  scene_id: "scene",
  version: 4,
  shot_number: 1,
  duration_seconds: "5",
  formal_video_artifact_id: "formal-A",
  formal_keyframe_artifact_id: null,
};
const target = {
  shotId: "s1",
  artifactId: "candidate-B",
  stage: "formal_video",
  reviewKind: "video_drift",
};
const json = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }),
  );
function show(search: ReviewTargetSearch) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRootRoute({
    component: () => (
      <QueryClientProvider client={client}>
        <ReviewWorkspace projectId="p1" targetSearch={search} />
      </QueryClientProvider>
    ),
  });
  render(
    <RouterProvider
      router={createRouter({
        routeTree: root,
        history: createMemoryHistory({ initialEntries: ["/"] }),
      })}
    />,
  );
}
afterEach(() => vi.restoreAllMocks());
function mockApi() {
  const writes: Record<string, unknown>[] = [];
  const summaries: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
    if (url.endsWith("/shots")) return json([shot]);
    if (url.endsWith("/workbench"))
      return json({
        shot,
        candidates: [
          {
            artifact_id: "candidate-B",
            artifact_type: "video",
            stage: "video",
            status: "completed",
          },
        ],
      });
    if (url.includes("/review-summary")) {
      summaries.push(url);
      return json({
        artifact_id: "candidate-B",
        review_node_run_id: "review-B",
        machine_status: "needs_human",
      });
    }
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      writes.push(body);
      return json({ ...body, id: "note", shot_id: "s1" });
    }
    if (url.endsWith("/repairs/r1"))
      return json({
        shot_id: "s1",
        steps: [{ id: "step1", stage: "video_rerun", result_artifact_id: "candidate-B" }],
      });
    if (url.endsWith("/annotations"))
      return json([
        {
          id: "old",
          artifact_id: "formal-A",
          target_kind: "video_time",
          note: "甲的批注",
          time_start: "0",
          time_end: null,
        },
      ]);
    return json({});
  });
  return { writes, summaries };
}
describe("exact review target", () => {
  it("binds a repair candidate's player, annotation and decision to B, never formal A", async () => {
    const { writes, summaries } = mockApi();
    show({ ...target, repairRequestId: "r1", repairStepId: "step1" });
    const player = await screen.findByLabelText("指定视频审片播放器");
    expect(player).toHaveAttribute("src", "/api/v1/projects/p1/artifacts/candidate-B/content");
    expect(screen.queryByText("甲的批注")).not.toBeInTheDocument();
    expect(summaries.every((url) => url.includes("artifact_id=candidate-B"))).toBe(true);
    Object.defineProperty(player, "duration", { value: 5, configurable: true });
    fireEvent.loadedMetadata(player);
    fireEvent.change(screen.getByLabelText("批注说明"), { target: { value: "乙的批注" } });
    fireEvent.click(screen.getByRole("button", { name: "保存视频批注" }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].artifact_id).toBe("candidate-B");
    fireEvent.change(screen.getByLabelText("视频漂移审查判断理由"), {
      target: { value: "乙通过" },
    });
    fireEvent.click(screen.getByTestId("review-approve-video_drift"));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1]).toMatchObject({ artifact_id: "candidate-B", review_node_run_id: "review-B" });
  });
  it.each([
    { ...target, artifactId: "absent" },
    { ...target, stage: "formal_keyframe" },
    { ...target, repairRequestId: "r1", repairStepId: "wrong-step" },
    { artifactId: "candidate-B" },
  ])("refuses an invalid explicit target instead of falling back", async (search) => {
    mockApi();
    show(search);
    expect(await screen.findByRole("alert")).toHaveTextContent("不会改为显示正式版本");
    expect(screen.queryByLabelText("正式视频审片播放器")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("指定视频审片播放器")).not.toBeInTheDocument();
  });
  it("preserves malformed search values and builds an encoded exact link", () => {
    expect(reviewTargetSearch({ artifactId: 3 })).toEqual({ artifactId: "" });
    expect(
      reviewTargetHref("p1", {
        shotId: "s1",
        artifactId: "b",
        stage: "formal_video",
        reviewKind: "video_drift",
      }),
    ).toContain("artifactId=b");
  });
});
