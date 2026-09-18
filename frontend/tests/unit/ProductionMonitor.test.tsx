import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterContextProvider,
} from "@tanstack/react-router";
import type { ReactElement } from "react";
import { fireEvent, render as renderView, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductionMonitor } from "../../src/features/production/ProductionMonitor";

function render(ui: ReactElement) {
  const router = createRouter({
    routeTree: createRootRoute(),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return renderView(ui, {
    wrapper: ({ children }) => (
      <RouterContextProvider router={router}>{children}</RouterContextProvider>
    ),
  });
}

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
    {
      id: "run-1",
      node_key: "video",
      status: "completed",
      attempt_no: 1,
      input_snapshot: { shot_id: "shot-1" },
    },
    {
      id: "run-2",
      node_key: "video",
      status: "failed",
      attempt_no: 1,
      input_snapshot: { shot_id: "shot-2" },
    },
    {
      id: "run-3",
      node_key: "subtitle",
      status: "queued",
      attempt_no: 1,
      input_snapshot: { shot_id: "shot-1" },
    },
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
    // Failures and scene risks have different units and may overlap.
    expect(screen.getByTestId("stat-failed").textContent).toBe("1");
    expect(screen.getByTestId("stat-risks").textContent).toBe("2");
    expect(screen.getByTestId("stat-artifacts").textContent).toBe("1");
    expect(screen.getByTestId("stat-experiments").textContent).toBe("3");

    expect(screen.getByTestId("monitor-scene-table")).toBeInTheDocument();
    expect(screen.getByText(/夜晚 ·/)).toBeInTheDocument();
    expect(screen.getByText(/白天 ·/)).toBeInTheDocument();
    const sceneLinks = within(screen.getByTestId("monitor-scene-table")).getAllByRole("link");
    expect(sceneLinks).toHaveLength(2);
    expect(sceneLinks[0]).toHaveTextContent("1.1 · 雨夜街口");
    expect(sceneLinks[0].getAttribute("href")).toContain("/projects/project-1/scenes/scene-1");
    expect(screen.queryByText("进入")).not.toBeInTheDocument();
    expect(screen.queryByTestId("shot-timeline")).not.toBeInTheDocument();
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

  it("does not report a failed attempt after the same node succeeds", () => {
    render(
      <ProductionMonitor
        projectId="project-1"
        scenes={[{ ...scenes[0], risk_count: 0 }]}
        shots={[shots[0]]}
        snapshot={
          {
            ...snapshot,
            node_runs: [
              {
                id: "retry-success",
                node_key: "composite",
                status: "completed",
                attempt_no: 2,
                input_snapshot: { shot_id: "shot-1", execution_branch: "formal" },
              },
              {
                id: "old-failure",
                node_key: "composite",
                status: "failed",
                attempt_no: 1,
                input_snapshot: { shot_id: "shot-1", execution_branch: "formal" },
              },
            ],
          } as never
        }
        experimentCount={0}
      />,
    );

    expect(screen.getByTestId("stat-completed")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-failed")).toHaveTextContent("0");
  });
});

it("filters risk scenes locally without changing the overview totals", () => {
  render(
    <ProductionMonitor
      projectId="project-1"
      scenes={scenes}
      shots={shots}
      snapshot={snapshot as never}
      experimentCount={0}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "仅看风险" }));
  expect(screen.queryByTestId("monitor-scene-scene-1")).not.toBeInTheDocument();
  expect(screen.getByTestId("monitor-scene-scene-2")).toBeInTheDocument();
  expect(screen.getByTestId("stat-scenes")).toHaveTextContent("2");
  expect(screen.getByTestId("stat-risks")).toHaveTextContent("2");
  fireEvent.click(screen.getByRole("button", { name: "全部场景" }));
  expect(screen.getByTestId("monitor-scene-scene-1")).toBeInTheDocument();
});

it("does not turn pending or failed queries into empty successful facts", () => {
  const { rerender } = render(
    <ProductionMonitor projectId="project-1" scenes={[]} shots={[]} scenesLoading shotsLoading />,
  );
  expect(screen.getByText("正在读取场景制作进度…")).toBeInTheDocument();
  expect(screen.getByTestId("stat-formal-videos")).toHaveTextContent("—");
  expect(screen.getByTestId("stat-failed")).toHaveTextContent("—");
  expect(screen.queryByText(/尚无场景/)).not.toBeInTheDocument();
  rerender(
    <ProductionMonitor
      projectId="project-1"
      scenes={[]}
      shots={[]}
      scenesError
      shotsError
      snapshotError
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("读取失败");
  expect(screen.getByTestId("stat-shots")).toHaveTextContent("—");
  expect(screen.queryByText(/尚无场景/)).not.toBeInTheDocument();
});

it("offers a next step for a zero-risk scene missing one formal video", () => {
  render(
    <ProductionMonitor
      projectId="project-1"
      scenes={[{ ...scenes[0], shot_count: 6, formal_keyframe_count: 6, formal_video_count: 5 }]}
      shots={shots}
      snapshot={snapshot as never}
    />,
  );
  expect(screen.getByTestId("production-next-step")).toHaveTextContent(
    "还有 1 个镜头未确认正式视频",
  );
  expect(screen.getByRole("link", { name: "继续制作" })).toHaveAttribute(
    "href",
    "/projects/project-1/scenes/scene-1",
  );
  fireEvent.click(screen.getByRole("button", { name: "未完成" }));
  expect(screen.getByTestId("monitor-scene-scene-1")).toBeInTheDocument();
  expect(screen.getByTestId("stat-risks")).toHaveTextContent("0");
});

it("makes failed executions inspectable without treating them as scene risks", () => {
  render(
    <ProductionMonitor
      projectId="project-1"
      scenes={[scenes[0]]}
      shots={shots}
      snapshot={snapshot as never}
    />,
  );
  fireEvent.click(screen.getByText("查看失败执行"));
  const target = screen.getByRole("link", { name: /查看镜头 2/ });
  expect(target).toHaveAttribute("href", "/projects/project-1/scenes/scene-1?shotId=shot-2");
  expect(screen.getByTestId("stat-risks")).toHaveTextContent("0");
});

it("only offers editing when every scene has formal products, including no empty scenes", () => {
  const complete = { ...scenes[0], formal_keyframe_count: 2, formal_video_count: 2 };
  const { rerender } = render(
    <ProductionMonitor projectId="project-1" scenes={[complete]} shots={shots} />,
  );
  expect(screen.getByRole("link", { name: "进入剪辑" })).toHaveAttribute(
    "href",
    "/projects/project-1/edit",
  );
  expect(screen.getByTestId("production-next-step")).not.toHaveTextContent("已导出成片");
  rerender(
    <ProductionMonitor
      projectId="project-1"
      scenes={[complete, { ...scenes[1], shot_count: 0, risk_count: 0 }]}
      shots={shots}
    />,
  );
  expect(screen.queryByRole("link", { name: "进入剪辑" })).not.toBeInTheDocument();
  expect(screen.getByTestId("production-next-step")).toHaveTextContent("先为场景添加镜头");
  expect(screen.getByRole("link", { name: "继续制作" })).toHaveAttribute(
    "href",
    "/projects/project-1/scenes/scene-2",
  );
});

it("prioritizes the scene with missing keyframes without guessing a shot from aggregate counts", () => {
  render(
    <ProductionMonitor
      projectId="project-1"
      scenes={[
        { ...scenes[0], formal_keyframe_count: 2 },
        { ...scenes[1], risk_count: 0 },
      ]}
      shots={[{ ...shots[0], id: "missing", scene_id: "scene-2" }]}
    />,
  );
  expect(screen.getByTestId("production-next-step")).toHaveTextContent("未确认正式关键帧");
  expect(screen.getByRole("link", { name: "继续制作" })).toHaveAttribute(
    "href",
    "/projects/project-1/scenes/scene-2",
  );
});

it("does not offer stale next steps or declare a stale filtered list complete after a query fails", () => {
  const props = {
    projectId: "project-1",
    scenes: [{ ...scenes[0], formal_keyframe_count: 2, formal_video_count: 2 }],
    shots,
  };
  const { rerender } = render(<ProductionMonitor {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "未完成" }));
  rerender(<ProductionMonitor {...props} scenesError />);
  expect(screen.queryByTestId("production-next-step")).not.toBeInTheDocument();
  expect(screen.queryByText("所有场景的正式产物均已齐备。")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("暂时无法判断筛选结果");
  fireEvent.click(screen.getByRole("button", { name: "全部场景" }));
  expect(screen.getByTestId("monitor-scene-scene-1")).toHaveTextContent("状态待刷新");
  expect(screen.getByTestId("monitor-scene-scene-1")).not.toHaveTextContent("2 / 2");
});

it("retains the chosen filter while refreshed scene facts update the next step", () => {
  const scene = { ...scenes[0], formal_keyframe_count: 2 };
  const { rerender } = render(
    <ProductionMonitor projectId="project-1" scenes={[scene]} shots={shots} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "未完成" }));
  rerender(
    <ProductionMonitor
      projectId="project-1"
      scenes={[{ ...scene, formal_video_count: 2 }]}
      shots={shots}
    />,
  );
  expect(screen.getByRole("button", { name: "未完成" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("status")).toHaveTextContent("所有场景的正式产物均已齐备");
  expect(screen.getByRole("link", { name: "进入剪辑" })).toBeInTheDocument();
});

it("distinguishes experiments and handles unlocatable runs without guessing a shot", () => {
  render(
    <ProductionMonitor
      projectId="project-1"
      scenes={scenes}
      shots={shots}
      snapshot={
        {
          ...snapshot,
          node_runs: [
            {
              ...snapshot.node_runs[1],
              input_snapshot: {
                shot_id: "removed",
                experiment_id: "exp-1",
                execution_branch: "experiment",
              },
            },
          ],
        } as never
      }
    />,
  );
  fireEvent.click(screen.getByText("查看失败执行"));
  const details = screen.getByRole("region", { name: "失败执行详情" });
  expect(details).toHaveTextContent("实验执行失败");
  expect(details).toHaveTextContent("暂无可定位的镜头");
  expect(within(details).queryByRole("link")).not.toBeInTheDocument();
});

it("prioritizes risks and navigates to a known failed shot without treating counts as additive", () => {
  render(
    <ProductionMonitor
      projectId="project-1"
      scenes={scenes}
      shots={[{ ...shots[0], scene_id: "scene-2", status: "failed" }]}
      snapshot={snapshot as never}
    />,
  );
  expect(screen.getByTestId("production-next-step")).toHaveTextContent("有 1 个场景存在风险");
  expect(screen.getByRole("link", { name: "检查风险场景" })).toHaveAttribute(
    "href",
    "/projects/project-1/scenes/scene-2?shotId=shot-1",
  );
  expect(screen.getByTestId("stat-risks")).toHaveTextContent("2");
  expect(screen.getByTestId("stat-failed")).toHaveTextContent("1");
});

it("hides failed-run details when the snapshot becomes unavailable while preserving scene facts", () => {
  const props = { projectId: "project-1", scenes, shots, snapshot: snapshot as never };
  const { rerender } = render(<ProductionMonitor {...props} />);
  fireEvent.click(screen.getByText("查看失败执行"));
  rerender(<ProductionMonitor {...props} snapshotError />);
  expect(screen.getByTestId("stat-failed")).toHaveTextContent("—");
  expect(screen.queryByRole("region", { name: "失败执行详情" })).not.toBeInTheDocument();
  expect(screen.getByTestId("production-next-step")).toBeInTheDocument();
  expect(screen.getByTestId("stat-formal-videos")).toHaveTextContent("1");
});
