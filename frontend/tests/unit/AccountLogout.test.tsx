import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountSettingsPage } from "../../src/routes/settings-page";
import {
  fetchCurrentUser,
  fetchHealth,
  logoutUser,
  setSelectedWorkspaceId,
} from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({
  fetchCurrentUser: vi.fn(),
  fetchHealth: vi.fn(),
  logoutUser: vi.fn(),
  getSelectedWorkspaceId: vi.fn(() => "workspace-1"),
  setSelectedWorkspaceId: vi.fn(),
  // The account page also mounts the recovery panel; it hides itself when the
  // owner-only query is not available.
  apiGet: vi.fn(() => Promise.reject(new Error("no recovery access"))),
  apiSend: vi.fn(),
  fetchCsrf: vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

describe("Account settings logout", () => {
  it("clears the session and the remembered workspace on explicit logout", async () => {
    vi.mocked(fetchCurrentUser).mockResolvedValue({
      id: "user-1",
      email: "owner@example.com",
      display_name: "Owner",
      created_at: "2026-01-01T00:00:00Z",
    } as never);
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", env: "test", version: "1" } as never);
    vi.mocked(logoutUser).mockResolvedValue(undefined);

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <AccountSettingsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("owner@example.com")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("logout-button"));

    await waitFor(() => expect(logoutUser).toHaveBeenCalledTimes(1));
    expect(setSelectedWorkspaceId).toHaveBeenCalledWith(null);
  });
});
