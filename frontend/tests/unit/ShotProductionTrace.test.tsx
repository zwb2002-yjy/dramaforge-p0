import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShotProductionTrace } from "../../src/features/shots/ShotProductionTrace";

const SHOT_ID = "58beaebf-6b5f-478a-873f-e1f828567492";

/**
 * Text a user sees without opening the collapsed diagnostics block.
 *
 * The plan's leak rule is about the ordinary surface; stored tokens are allowed
 * inside a clearly marked, collapsed, read-only diagnostics block.
 */
function ordinarySurfaceText(): string {
  const clone = screen.getByTestId("shot-production-trace").cloneNode(true) as HTMLElement;
  clone.querySelectorAll("details").forEach((element) => element.remove());
  return clone.textContent ?? "";
}

describe("ShotProductionTrace", () => {
  it("explains a failed run in product wording instead of the stored tokens", () => {
    render(
      <ShotProductionTrace
        shotId={SHOT_ID}
        trace={[
          {
            node_run_id: "089dbe7a-a8bd-407d-aa3d-6110b7edef79",
            node_key: "video",
            status: "failed",
            error_code: "UPSTREAM_TERMINAL_FAILURE",
            error_summary: "required upstream keyframe ended with failed",
          },
        ]}
      />,
    );

    const surface = screen.getByTestId("shot-production-trace");
    // Node and status come from the shared Chinese vocabulary.
    expect(surface).toHaveTextContent("视频");
    expect(surface).toHaveTextContent("失败");
    // A structured upstream failure becomes a sentence, not a code.
    expect(screen.getByTestId("shot-production-failure")).toHaveTextContent(
      "必需上游「关键帧」已失败",
    );
    const visible = ordinarySurfaceText();
    expect(visible).not.toContain("UPSTREAM_TERMINAL_FAILURE");
    expect(visible).not.toContain("required upstream");
    expect(visible).not.toContain("089dbe7a");
    expect(visible).not.toContain("failed");
  });

  it("keeps stored tokens and provider text inside the collapsed diagnostics", () => {
    render(
      <ShotProductionTrace
        shotId={SHOT_ID}
        trace={[
          {
            node_run_id: "089dbe7a-a8bd-407d-aa3d-6110b7edef79",
            node_key: "keyframe",
            status: "failed",
            error_code: "WORKER_ERROR",
            error_summary: "selected model binding is not eligible for this intent",
          },
        ]}
      />,
    );

    // An unmapped provider message would be English on the ordinary surface, so
    // only the Chinese product phrase is shown there.
    const failure = screen.getByTestId("shot-production-failure");
    expect(failure).toHaveTextContent("执行失败");
    expect(failure).not.toHaveTextContent("WORKER_ERROR");
    expect(failure).not.toHaveTextContent("selected model binding");

    const diagnostics = screen.getByTestId("shot-production-trace-diagnostics");
    expect(diagnostics).toHaveTextContent("WORKER_ERROR");
    expect(diagnostics).toHaveTextContent("selected model binding is not eligible");
    expect(diagnostics).toHaveTextContent("089dbe7a");
    // The diagnostics block is collapsed until the user asks for it.
    expect(diagnostics).not.toHaveAttribute("open");
  });

  it("renders an empty state and still reports the run to the caller", () => {
    const onSelectRun = vi.fn();
    const { rerender } = render(
      <ShotProductionTrace shotId={SHOT_ID} trace={[]} onSelectRun={onSelectRun} />,
    );
    expect(screen.getByText("该镜头尚无执行记录。")).toBeInTheDocument();

    rerender(
      <ShotProductionTrace
        shotId={SHOT_ID}
        trace={[
          {
            node_run_id: "11111111-1111-4111-8111-111111111111",
            node_key: "keyframe",
            status: "completed",
          },
        ]}
        onSelectRun={onSelectRun}
      />,
    );
    const button = screen.getByRole("button", { name: "查看完整证据" });
    button.click();
    expect(onSelectRun).toHaveBeenCalledWith("11111111-1111-4111-8111-111111111111");
    expect(screen.getByTestId("shot-production-trace")).toHaveTextContent("已完成");
  });
});
