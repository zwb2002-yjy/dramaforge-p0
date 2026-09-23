import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewEvidenceStrip } from "../../src/features/review/ReviewEvidenceStrip";

const summary = (frames: unknown[]) => ({
  shot_id: "s1",
  artifact_id: "video-b",
  review_kind: "video_drift",
  node_key: "video_drift_review",
  review_node_run_id: "run-review",
  review_artifact_id: "evidence",
  machine_status: "needs_human",
  decision: null,
  decision_reason: null,
  applies: false,
  blocked_reason: "REVIEW_AWAITING_HUMAN",
  allowed_actions: ["approve", "reject"],
  shot_version: 1,
  evidence: {
    source_artifact_id: "video-b",
    source_content_hash: "b".repeat(64),
    review_node_run_id: "run-review",
    review_artifact_id: "evidence",
    sampling_version: "opencv-start-mid-end-scene-v1",
    canonical_artifact_id: "keyframe-a",
    canonical_content_hash: "a".repeat(64),
    frames,
  },
});
const json = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }),
  );
function renderStrip() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReviewEvidenceStrip
        projectId="p1"
        shotId="s1"
        artifactId="video-b"
        reviewKind="video_drift"
        stage="formal_video"
        onSelectTime={vi.fn()}
      />
    </QueryClientProvider>,
  );
}
afterEach(() => vi.restoreAllMocks());
describe("ReviewEvidenceStrip", () => {
  it("renders sorted immutable evidence and only seeks on frame click", async () => {
    const seeks = vi.fn();
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json(
        summary([
          {
            sample_id: "mid@1",
            role: "mid",
            timestamp_seconds: 1,
            frame_content_hash: "b",
            delivery_path: "/mid",
            status: "available_for_human_review",
          },
          {
            sample_id: "start@0",
            role: "start",
            timestamp_seconds: 0,
            frame_content_hash: "a",
            delivery_path: "/start",
            status: "available_for_human_review",
          },
          {
            sample_id: "end@2",
            role: "end",
            timestamp_seconds: 2,
            frame_content_hash: "c",
            delivery_path: "/end",
            status: "available_for_human_review",
          },
        ]),
      ),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ReviewEvidenceStrip
          projectId="p1"
          shotId="s1"
          artifactId="video-b"
          reviewKind="video_drift"
          stage="formal_video"
          onSelectTime={seeks}
        />
      </QueryClientProvider>,
    );
    await screen.findByTestId("review-evidence-strip");
    const figures = screen.getAllByRole("figure");
    expect(figures.map((figure) => figure.textContent)).toEqual([
      "start · 0.000s",
      "mid · 1.000s",
      "end · 2.000s",
    ]);
    expect(seeks).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "定位mid 1秒" }));
    expect(seeks).toHaveBeenCalledWith(1);
  });
  it("distinguishes missing automatic frame samples from a missing video", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(summary([])));
    renderStrip();
    expect(await screen.findByTestId("review-evidence-empty")).toHaveTextContent(
      "暂无自动抽帧检查结果，可直接播放下方视频并进行人工审片。",
    );
    expect(screen.queryByText("当前没有可用的视频证据。")).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
  it("shows unavailable evidence without manufacturing a frame or request", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json(
        summary([
          {
            sample_id: "mid@1",
            role: "mid",
            timestamp_seconds: 1,
            frame_content_hash: null,
            delivery_path: null,
            status: "unavailable",
            unavailable_reason: "无法解码",
          },
        ]),
      ),
    );
    renderStrip();
    expect(await screen.findByText("证据不可用")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
