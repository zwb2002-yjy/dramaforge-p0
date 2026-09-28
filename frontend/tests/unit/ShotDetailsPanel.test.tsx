import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShotDetailsPanel } from "../../src/features/shots/ShotDetailsPanel";

const SHOT = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 3,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "",
  duration_seconds: "4",
  status: "draft",
  sort_order: 3,
  version: 7,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: "formal-kf",
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

describe("ShotDetailsPanel", () => {
  it("renders nothing until the details sheet is opened", () => {
    render(<ShotDetailsPanel open={false} shot={SHOT} trace={[]} onClose={vi.fn()} />);
    expect(screen.queryByTestId("shot-details-sheet")).not.toBeInTheDocument();
  });

  it("surfaces shot metadata and production trace on demand", () => {
    const onClose = vi.fn();
    render(
      <ShotDetailsPanel
        open
        shot={SHOT}
        trace={[{ node_run_id: "run-1", node_key: "keyframe", status: "completed" }]}
        onClose={onClose}
      />,
    );

    const sheet = screen.getByTestId("shot-details-sheet");
    expect(sheet).toHaveAttribute("data-shot-id", "shot-1");
    expect(sheet).toHaveTextContent("#3 · v7");
    // Status and confirmed artifacts speak product vocabulary; the stored tokens
    // and artifact ids stay in the collapsed diagnostics block.
    expect(screen.getByTestId("shot-details-status")).toHaveTextContent("草稿");
    const body = (() => {
      const clone = sheet.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("details").forEach((element) => element.remove());
      return clone.textContent ?? "";
    })();
    expect(body).toContain("已确认");
    expect(body).toContain("未确认");
    expect(body).not.toContain("formal-kf");
    expect(body).not.toContain("draft");
    const ownDiagnostics = screen.getByTestId("shot-details-diagnostics");
    expect(ownDiagnostics).toHaveTextContent("formal-kf");
    expect(ownDiagnostics).not.toHaveAttribute("open");
    expect(screen.getByTestId("shot-production-trace")).toHaveAttribute("data-shot-id", "shot-1");
    // The trace speaks product vocabulary; the stored token stays in the
    // collapsed diagnostics block instead of the ordinary surface.
    const trace = screen.getByTestId("shot-production-trace");
    const visible = (() => {
      const clone = trace.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("details").forEach((element) => element.remove());
      return clone.textContent ?? "";
    })();
    expect(visible).toContain("已完成");
    expect(visible).not.toContain("completed");

    fireEvent.click(screen.getByTestId("shot-details-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
