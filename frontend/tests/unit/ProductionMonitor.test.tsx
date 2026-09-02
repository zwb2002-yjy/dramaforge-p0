import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductionMonitor } from "../../src/features/production/ProductionMonitor";

const scenes = [
  {
    id: "scene-1",
    project_id: "project-1",
    episode_id: "episode-1",
    episode_number: 1,
    scene_number: 1,
    location_name: "雨夜街口",
    time_of_day: "night",
    synopsis: "",
    version: 1,
    shot_count: 2,
    formal_keyframe_count: 1,
    formal_video_count: 1,
    risk_count: 0,
    representative_artifact: null,
  },
  {
    id: "scene-2",
    project_id: "project-1",
    episode_id: "episode-1",
    episode_number: 1,
    scene_number: 2,
    location_name: "旧公寓",
    time_of_day: "day",
    synopsis: "",
    version: 1,
    shot_count: 1,
    formal_keyframe_count: 0,
    formal_video_count: 0,
    risk_count: 2,
    representative_artifact: null,
  },
];

const shots = [
  {
    id: "shot-1",
    scene_id: "scene-1",
    shot_number: 1,
    sort_order: 1,
    shot_type: "中近景",
    status: "draft",
  },
  {
    id: "shot-2",
    scene_id: "scene-1",
    shot_number: 2,
    sort_order: 2,
    shot_type: "特写",
    status: "completed",
  },
];

const snapshot = {
  project_id: "project-1",
  name: "验收",
  node_runs: [
    { id: "run-1", node_key: "video", status: "completed", attempt_no: 1 },
    { id: "run-2", node_key: "video", status: "failed", attempt_no: 1 },
    { id: "run-3", node_key: "subtitle", status: "queued", attempt_no: 1 },
  ],
  artifacts: [{ id: "art-1", object_key: "kf/art-1.png", byte_size: 10 }],
  provider_operations: [],
};

describe("ProductionMonitor", () => {
  it("renders cross-scene summary stats and per-scene rows", () => {
    render(
      <ProductionMonitor
        projectId="project-1"
        scenes={scenes}
        shots={shots}
        snapshot={snapshot as never}
        experimentCount={3}
      />,
    );

    expect(screen.getByTestId("production-monitor")).toBeInTheDocument();
    expect(screen.getByTestId("stat-scenes").textContent).toBe("2");
    expect(screen.getByTestId("stat-shots").textContent).toBe("2");
    expect(screen.getByTestId("stat-formal-keyframes").textContent).toBe("1");
    expect(screen.getByTestId("stat-formal-videos").textContent).toBe("1");
    expect(screen.getByTestId("stat-completed").textContent).toBe("1");
    expect(screen.getByTestId("stat-running").textContent).toBe("1");
    // failed runs + scene risks
    expect(screen.getByTestId("stat-failed").textContent).toBe("3");
    expect(screen.getByTestId("stat-artifacts").textContent).toBe("1");
    expect(screen.getByTestId("stat-experiments").textContent).toBe("3");

    expect(screen.getByTestId("monitor-scene-table")).toBeInTheDocument();
    expect(screen.getByText("1.1 · 雨夜街口")).toBeInTheDocument();
    expect(screen.getByText("1.2 · 旧公寓")).toBeInTheDocument();
    const sceneLinks = screen.getAllByRole("link", { name: "场景工作区" });
    expect(sceneLinks).toHaveLength(2);
    expect(sceneLinks[0].getAttribute("href")).toContain("/projects/project-1/scenes/scene-1");
  });

  it("renders empty state when no scenes exist", () => {
    render(
      <ProductionMonitor
        projectId="project-1"
        scenes={[]}
        shots={[]}
        snapshot={undefined}
        experimentCount={0}
      />,
    );
    expect(screen.getByText("尚无场景。请在场景工作区创建场景与镜头。")).toBeInTheDocument();
  });
});
