import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdvancedRecoveryPanel } from "../../src/features/maintenance/AdvancedRecoveryPanel";
import { fetchRecoveryItems, replayRecoveryItem } from "../../src/features/maintenance/api";

vi.mock("../../src/features/maintenance/api", () => ({
  fetchRecoveryItems: vi.fn(),
  replayRecoveryItem: vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

function renderPanel() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AdvancedRecoveryPanel />
    </QueryClientProvider>,
  );
}

const wakeupItem = {
  kind: "director_wakeup" as const,
  id: "inbox-1",
  project_id: "project-1",
  label: "director.wakeup",
  detail: "RuntimeError",
  attempts: 5,
  failed_at: "2026-09-17T08:00:00Z",
};

describe("AdvancedRecoveryPanel", () => {
  it("stays invisible while there is no persisted failure", async () => {
    vi.mocked(fetchRecoveryItems).mockResolvedValue({ items: [] });
    renderPanel();
    await waitFor(() => expect(fetchRecoveryItems).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("advanced-recovery-panel")).not.toBeInTheDocument();
  });

  it("replays one item with the failure identity it displayed", async () => {
    vi.mocked(fetchRecoveryItems).mockResolvedValue({ items: [wakeupItem] });
    vi.mocked(replayRecoveryItem).mockResolvedValue({
      kind: "director_wakeup",
      id: "inbox-1",
      applied: true,
      replayed_at: "2026-09-17T08:05:00Z",
    });

    renderPanel();
    const panel = await screen.findByTestId("advanced-recovery-panel");
    expect(panel).toHaveTextContent("导演唤醒失败");
    fireEvent.click(screen.getByRole("button", { name: "重放这一项" }));

    await waitFor(() => expect(replayRecoveryItem).toHaveBeenCalledTimes(1));
    expect(vi.mocked(replayRecoveryItem).mock.calls[0][0]).toEqual(wakeupItem);
    expect(await screen.findByText("已提交重放。")).toBeInTheDocument();
  });

  it("surfaces a stale-identity conflict instead of retrying blind", async () => {
    vi.mocked(fetchRecoveryItems).mockResolvedValue({ items: [wakeupItem] });
    vi.mocked(replayRecoveryItem).mockRejectedValue(
      new Error("Director wakeup failure changed; reload before replay"),
    );

    renderPanel();
    await screen.findByTestId("advanced-recovery-panel");
    fireEvent.click(screen.getByRole("button", { name: "重放这一项" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Director wakeup failure changed; reload before replay",
    );
  });
});
