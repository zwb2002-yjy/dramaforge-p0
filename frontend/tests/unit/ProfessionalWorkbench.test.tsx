import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProfessionalWorkbench } from "../../src/features/production/ProfessionalWorkbench";

const shots = [
  {
    id: "shot-1",
    scene_id: "scene-1",
    shot_number: 1,
    shot_type: "中近景",
    visual_description: "主角站在雨夜街口，抬头看向霓虹灯。",
    dialogue: "我终于明白了。",
    sort_order: 1,
    status: "draft",
    version: 1,
  },
  {
    id: "shot-2",
    scene_id: "scene-1",
    shot_number: 2,
    shot_type: "特写",
    visual_description: "手里的旧照片被雨水打湿。",
    dialogue: "",
    sort_order: 2,
    status: "completed",
    version: 1,
  },
];

describe("ProfessionalWorkbench", () => {
  it("keeps canvas edits explicit and assistant suggestions opt-in", async () => {
    const onSelectShot = vi.fn();
    render(
      <ProfessionalWorkbench
        projectId="project-1"
        shots={shots}
        selectedShotId="shot-1"
        onSelectShot={onSelectShot}

        onSave={async (shot) => ({ ...shot, version: shot.version + 1 })}
      />,
    );

    expect(screen.getByTestId("professional-workbench")).toBeInTheDocument();
    expect(screen.getByText("正式事实源")).toBeInTheDocument();
    expect(screen.queryByText("补齐动作因果")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开当前镜头的导演建议" })).toHaveAttribute(
      "href",
      "/projects/project-1/scenes/scene-1?shotId=shot-1&tool=director",
    );

    const editor = screen.getByRole("textbox", { name: "镜头导演语义" });
    fireEvent.change(editor, { target: { value: "用户手动改写的正式镜头语义" } });
    expect(screen.getByText("有未保存变更")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "打开当前镜头的导演建议" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存画布版本" }));
    await waitFor(() =>
      expect(screen.getByText(/后续执行将以这份正式镜头语义为事实源/)).toBeInTheDocument(),
    );
  });

  it("does not fabricate detected facts or edit the canvas on entry", () => {
    render(
      <ProfessionalWorkbench
        projectId="project-1"
        shots={shots}
        selectedShotId="shot-1"
        onSelectShot={() => undefined}
      />,
    );
    const editor = screen.getByRole("textbox", { name: "镜头导演语义" });
    expect(editor).toHaveValue(shots[0].visual_description);
    expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
    expect(screen.queryByText(/检测到该镜头包含主角/)).not.toBeInTheDocument();
    expect(screen.queryByText("补齐动作因果")).not.toBeInTheDocument();
    expect(editor).toHaveValue(shots[0].visual_description);
  });

  it("uses the latest retry when labeling the current shot status", () => {
    render(
      <ProfessionalWorkbench
        projectId="project-1"
        shots={shots}
        selectedShotId="shot-1"
        onSelectShot={() => undefined}
        snapshot={
          {
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
      />,
    );

    expect(
      screen.getByRole("button", {
        name: /01 中近景 我终于明白了。 已完成/,
      }),
    ).toBeInTheDocument();
  });
});
