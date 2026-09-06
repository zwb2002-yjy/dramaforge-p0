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
import { VideoReviewTimeline } from "../../src/features/review/VideoReviewTimeline";

const shot = (id = "s1") => ({
  id,
  project_id: "p1",
  scene_id: "scene-1",
  shot_number: 1,
  duration_seconds: "5",
  visual_description: `Shot ${id}`,
  formal_video_artifact_id: `video-${id}`,
  formal_keyframe_artifact_id: null,
});
const json = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
function loadedVideo() {
  const player = screen.getByLabelText("正式视频审片播放器") as HTMLVideoElement;
  Object.defineProperty(player, "duration", { value: 5, configurable: true });
  fireEvent.loadedMetadata(player);
  return player;
}
afterEach(() => vi.restoreAllMocks());

describe("Video review interaction", () => {
  it("plays/selects locally and persists only an explicit valid time range", async () => {
    const writes: Array<Record<string, unknown>> = [];
    let saved: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test" });
      if (url.endsWith("/shots")) return json([shot(), shot("s2")]);
      if (url.endsWith("/workbench"))
        return json({ shot: shot(url.includes("/s2/") ? "s2" : "s1") });
      if (url.endsWith("/annotations")) {
        if (method === "POST") {
          const body = JSON.parse(String(init?.body));
          writes.push(body);
          saved = [{ ...body, id: "note-1", shot_id: "s1" }];
          return json(saved[0], 201);
        }
        return json(url.includes("/s1/") ? saved : []);
      }
      return json({}, 404);
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const root = createRootRoute({
      component: () => (
        <QueryClientProvider client={client}>
          <ReviewWorkspace projectId="p1" />
        </QueryClientProvider>
      ),
    });
    const router = createRouter({
      routeTree: root,
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });
    render(<RouterProvider router={router} />);
    await screen.findByLabelText("正式视频审片播放器");
    const player = loadedVideo();
    expect(player).toHaveAttribute("src", "/api/v1/projects/p1/artifacts/video-s1/content");
    player.currentTime = 1.25;
    fireEvent.timeUpdate(player);
    fireEvent.click(screen.getByRole("button", { name: "使用当前时间作为开始" }));
    fireEvent.change(screen.getByLabelText("视频批注类型"), { target: { value: "range" } });
    fireEvent.change(screen.getByLabelText("批注结束时间"), { target: { value: "2.5" } });
    fireEvent.change(screen.getByLabelText("批注说明"), { target: { value: "检查人物漂移" } });
    expect(writes).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "保存视频批注" }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toMatchObject({
      artifact_id: "video-s1",
      target_kind: "video_time",
      time_start: "1.25",
      time_end: "2.5",
      note: "检查人物漂移",
    });
    expect(await screen.findByText(/1.25s–2.50s/)).toBeInTheDocument();
    expect(screen.getByLabelText("批注说明")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("当前镜头"), { target: { value: "s2" } });
    await waitFor(() =>
      expect(screen.getByLabelText("正式视频审片播放器")).toHaveAttribute(
        "src",
        "/api/v1/projects/p1/artifacts/video-s2/content",
      ),
    );
    expect(screen.getByLabelText("批注开始时间")).toHaveValue(0);
    expect(screen.queryByText(/1.25s–2.50s/)).not.toBeInTheDocument();
  });
  it("rejects out-of-duration and reversed ranges and disables saving broken media", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <VideoReviewTimeline
        videoUrl="/video.mp4"
        durationSeconds={5}
        annotations={[]}
        note="note"
        onAddAnnotation={save}
      />,
    );
    const player = loadedVideo();
    fireEvent.change(screen.getByLabelText("视频批注类型"), { target: { value: "range" } });
    fireEvent.change(screen.getByLabelText("批注开始时间"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("批注结束时间"), { target: { value: "2" } });
    expect(screen.getByRole("button", { name: "保存视频批注" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("批注结束时间"), { target: { value: "6" } });
    expect(screen.getByRole("button", { name: "保存视频批注" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("批注结束时间"), { target: { value: "4" } });
    expect(screen.getByRole("button", { name: "保存视频批注" })).toBeEnabled();
    fireEvent.error(player);
    expect(screen.getByRole("alert")).toHaveTextContent("无法加载正式视频");
    expect(screen.getByRole("button", { name: "保存视频批注" })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
  });
  it("sends a single point with a null end only on Save", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <VideoReviewTimeline
        videoUrl="/video.mp4"
        durationSeconds={5}
        annotations={[]}
        note="point"
        onAddAnnotation={save}
      />,
    );
    loadedVideo();
    fireEvent.change(screen.getByLabelText("批注开始时间"), { target: { value: "1.5" } });
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存视频批注" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(1.5, null));
  });
});
