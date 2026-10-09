import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SceneMediaGallery } from "../../src/features/scenes/SceneMediaGallery";
import type { SceneSummary, ShotLite } from "../../src/features/scenes/api";

const scene: SceneSummary = {
  id: "scene-1",
  episode_id: "episode-1",
  episode_number: 1,
  scene_number: 1,
  location_name: "乌镇",
  time_of_day: "day",
  synopsis: "",
  version: 1,
  shot_count: 6,
  formal_keyframe_count: 6,
  formal_video_count: 5,
  risk_count: 0,
  representative_artifact: null,
};
const shots: ShotLite[] = Array.from({ length: 6 }, (_, index) => ({
  id: `shot-${index + 1}`,
  project_id: "project-1",
  scene_id: scene.id,
  shot_number: index + 1,
  shot_type: "wide",
  camera_move: "static",
  visual_description: `画面 ${index + 1}`,
  dialogue: "",
  duration_seconds: "3",
  status: "ready",
  sort_order: index,
  version: 1,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: `frame-${index + 1}`,
  formal_video_artifact_id: index < 5 ? `video-${index + 1}` : null,
  formal_composite_artifact_id: null,
}));
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SceneMediaGallery projectId="project-1" scene={scene} />
    </QueryClientProvider>,
  );
}
afterEach(() => vi.restoreAllMocks());
it("exposes all six shots, six frame actions and five playable videos without writes", async () => {
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify({ shots }), { headers: { "Content-Type": "application/json" } }),
    );
  mount();
  const list = await screen.findByRole("list", { name: "场景镜头列表" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(6);
  expect(within(list).getAllByRole("img")).toHaveLength(6);
  expect(screen.getByRole("tab", { name: "6 镜头" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tab", { name: "6 关键帧" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "5 视频" })).toBeInTheDocument();
  expect(
    screen
      .getAllByRole("button", { name: /^播放视频 · 镜头/ })
      .filter((b) => !b.hasAttribute("disabled")),
  ).toHaveLength(5);
  expect(screen.getByRole("button", { name: "播放视频 · 镜头 6" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "编辑镜头 6" })).toHaveAttribute(
    "href",
    "/projects/project-1/scenes/scene-1?shotId=shot-6",
  );
  expect(fetch.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
});
it("does not label loading data as missing media", () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
  mount();
  expect(screen.getByRole("status")).toHaveTextContent("正在读取镜头与素材");
  expect(screen.queryByText("此场景尚无镜头。")).not.toBeInTheDocument();
});
it("keeps read failure distinct from an empty scene", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 503 }));
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("不能据此判断素材缺失");
  expect(screen.queryByText("此场景尚无镜头。")).not.toBeInTheDocument();
});
it("shows an explicit empty scene after a successful read", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ shots: [] }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  mount();
  expect(await screen.findByText("此场景尚无镜头。")).toBeInTheDocument();
});
