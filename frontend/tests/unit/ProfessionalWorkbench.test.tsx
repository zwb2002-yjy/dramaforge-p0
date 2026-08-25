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

        onSave={async (shot) => ({ ...shot, version: shot.version + 1 })}      />,
    );

    expect(screen.getByTestId("professional-workbench")).toBeInTheDocument();
    expect(screen.getByText("正式事实源")).toBeInTheDocument();
    expect(screen.getByText("补齐动作因果")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "采纳" })[0]);
    await waitFor(() => expect(screen.getByText("已采纳")).toBeInTheDocument());
    expect(screen.getByText(/保存画布后才会成为正式事实/)).toBeInTheDocument();

    const editor = screen.getByRole("textbox", { name: "镜头导演语义" });
    fireEvent.change(editor, { target: { value: "用户手动改写的正式镜头语义" } });
    expect(screen.getByText("有未保存变更")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存画布版本" }));
    await waitFor(() => expect(screen.getByText(/后续执行将以这份正式镜头语义为事实源/)).toBeInTheDocument());
  });

  it("lets the user reject a suggestion without changing the canvas", () => {
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
    fireEvent.click(screen.getAllByRole("button", { name: "拒绝" })[0]);
    expect(screen.queryByText("补齐动作因果")).not.toBeInTheDocument();
    expect(editor).toHaveValue(shots[0].visual_description);
  });
});
