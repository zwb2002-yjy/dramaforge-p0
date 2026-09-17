import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotChangeProposalsPanel } from "../../src/features/shots/ShotChangeProposalsPanel";
import {
  confirmShotChangeProposal,
  listShotChangeProposals,
} from "../../src/features/shots/changeProposalsApi";

vi.mock("../../src/features/shots/changeProposalsApi", () => ({
  listShotChangeProposals: vi.fn(),
  confirmShotChangeProposal: vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

function proposal(overrides: Record<string, unknown> = {}) {
  return {
    id: "proposal-1",
    shot_id: "shot-1",
    summary: "收紧镜头景别",
    base_shot_version: 3,
    replacement_payload: { shot_type: "close_up" },
    affected_node_keys: ["keyframe"],
    reusable_artifact_ids: [],
    status: "awaiting_confirmation",
    confirmed_revision_id: null,
    created_at: "2026-01-01T00:00:00Z",
    confirmed_at: null,
    ...overrides,
  };
}

function renderPanel(shotVersion = 3) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ShotChangeProposalsPanel projectId="project-1" shotId="shot-1" shotVersion={shotVersion} />
    </QueryClientProvider>,
  );
}

describe("ShotChangeProposalsPanel", () => {
  it("confirms a pending proposal through the explicit apply gate", async () => {
    vi.mocked(listShotChangeProposals).mockResolvedValue([proposal()]);
    vi.mocked(confirmShotChangeProposal).mockResolvedValue(
      proposal({ status: "applied", confirmed_revision_id: "rev-1" }),
    );

    renderPanel();
    expect(await screen.findByTestId("shot-change-proposal")).toHaveTextContent("收紧镜头景别");

    fireEvent.click(screen.getByTestId("confirm-shot-change-proposal"));

    await waitFor(() =>
      expect(confirmShotChangeProposal).toHaveBeenCalledWith("project-1", "shot-1", "proposal-1"),
    );
  });

  it("fails closed when the proposal base version is stale", async () => {
    vi.mocked(listShotChangeProposals).mockResolvedValue([proposal({ base_shot_version: 2 })]);

    renderPanel(5);

    expect(await screen.findByText("镜头已更新，需重新生成提案")).toBeInTheDocument();
    expect(screen.getByTestId("confirm-shot-change-proposal")).toBeDisabled();
  });

  it("reports an empty pending list without inventing proposals", async () => {
    vi.mocked(listShotChangeProposals).mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByTestId("shot-change-proposals-empty")).toBeInTheDocument();
  });
});
