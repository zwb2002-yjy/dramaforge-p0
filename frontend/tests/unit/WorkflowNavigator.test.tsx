import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowNavigator } from "../../src/features/production/WorkflowNavigator";
import type { WorkflowOverviewRead } from "../../src/features/production/workflow-api";

function overview(status: string): WorkflowOverviewRead {
  return {
    project_id: "project-1",
    episodes: [
      {
        episode_id: "episode-1",
        episode_number: 1,
        title: "雨后书店",
        synopsis: "",
        scene_count: 1,
        total_shots: 1,
      },
    ],
    scenes: [
      {
        scene_id: "scene-1",
        episode_id: "episode-1",
        episode_number: 1,
        scene_number: 1,
        location_name: "书店",
        time_of_day: "day",
        synopsis: "",
        production_status: {
          scene_id: "scene-1",
          episode_id: "episode-1",
          state: "complete",
          total_shots: 1,
          formal_shots: 1,
          failed_shots: 0,
          review_required: 0,
          blocked_shots: 0,
          reasons: [],
        },
        shots: [
          {
            shot_id: "shot-1",
            scene_id: "scene-1",
            episode_id: "episode-1",
            shot_number: 1,
            status,
            workflow_template_key: null,
            template_version: null,
            template_contract_hash: null,
            template_resolution_status: "NONE",
            quality_policy_id: null,
            repair_policy_id: null,
            required_reference_roles: [],
            supported_character_count: [],
            intent_tags: [],
            participations: [],
            capability_assessment: null,
          },
        ],
      },
    ],
    total_shots: 1,
    formal_shots: 1,
    blocked_scenes: 0,
    review_required_scenes: 0,
    unsupported_capability_shots: 0,
    available_staged_strategies: [],
  };
}

function mount(status: string) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ overview: overview(status) }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowNavigator projectId="project-1" />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("WorkflowNavigator stored shot states", () => {
  it.each([
    ["in_production", "制作中"],
    ["review_passed", "审查已通过"],
    ["review_rejected", "审查未通过"],
    ["pending", "待处理"],
  ])("keeps %s distinct from the scene's formal completion", async (status, label) => {
    mount(status);
    const row = await screen.findByTestId("workflow-shot-1");
    expect(row).toHaveTextContent(`创作：${label}`);
    expect(row).not.toHaveTextContent("待确认");
    expect(row).not.toHaveTextContent("已完成");
    expect(row).toHaveTextContent("未使用模板");
    expect(within(screen.getByTestId("workflow-scene-1")).getByText("完成")).toBeInTheDocument();
    expect(
      screen.getByText("场景完成按正式视频统计；镜头创作状态不代表有任务正在运行。"),
    ).toBeInTheDocument();
  });

  it("does not infer completion for an unknown stored state", async () => {
    mount("future_state");
    const row = await screen.findByTestId("workflow-shot-1");
    expect(row).toHaveTextContent("创作：状态待同步");
    expect(row).not.toHaveTextContent("future_state");
    expect(row).not.toHaveTextContent("已完成");
  });
});
