import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DirectorTurnStatus } from "../../src/features/director/DirectorTurnStatus";

const TURN = {
  id: "66666666-6666-4666-8666-666666666666",
  status: "awaiting_user",
  wait_reason: "context_changed",
  step_count: 4,
  revision: 7,
  runtime_revision: null,
  last_error: null,
  intent_snapshot: { user_instruction: "保持纪实自然" },
  request_summary: {},
  response_summary: {},
  output_snapshot: {},
};

function turn(overrides: Record<string, unknown>) {
  return { ...TURN, ...overrides } as never;
}

function renderStatus(rows: unknown[]) {
  render(
    <DirectorTurnStatus
      turns={rows as never}
      loading={false}
      syncError={null}
      busyTurnId={null}
      onStop={vi.fn()}
      onResume={vi.fn()}
    />,
  );
}

/** Text a user sees without opening the collapsed diagnostics block. */
function ordinarySurfaceText(): string {
  const clone = screen.getByTestId("director-turn-status").cloneNode(true) as HTMLElement;
  clone.querySelectorAll("details").forEach((element) => element.remove());
  return clone.textContent ?? "";
}

describe("DirectorTurnStatus product vocabulary", () => {
  it("explains a stored wait reason instead of printing the token", () => {
    renderStatus([turn({})]);

    expect(screen.getByTestId("director-wait-reason")).toHaveTextContent(
      "镜头或场景事实已变化，等待重新对齐",
    );
    expect(ordinarySurfaceText()).not.toContain("context_changed");
  });

  it("never falls back to the raw token for an unknown reason or status", () => {
    renderStatus([turn({ wait_reason: "some_new_runtime_reason", status: "some_new_status" })]);

    expect(screen.getByTestId("director-wait-reason")).toHaveTextContent("等待导演继续");
    const visible = ordinarySurfaceText();
    expect(visible).not.toContain("some_new_runtime_reason");
    expect(visible).not.toContain("some_new_status");
    // The stored values stay available where diagnostics belong.
    const diagnostics = screen.getByTestId("director-turn-diagnostics");
    expect(diagnostics).toHaveTextContent("some_new_runtime_reason");
    expect(diagnostics).toHaveTextContent("some_new_status");
    expect(diagnostics).not.toHaveAttribute("open");
    expect(diagnostics.querySelector("summary")).toHaveTextContent("开发 / 诊断详情（只读）");
  });

  it("keeps the stopped-turn summary in creative language", () => {
    renderStatus([turn({ status: "failed", last_error: "step_limit_reached at step 4" })]);

    expect(screen.getByTestId("director-stop-summary")).toHaveTextContent(
      "本轮导演协作步数已用完，确认后可继续。",
    );
    expect(ordinarySurfaceText()).not.toContain("step_limit_reached");
  });
});
