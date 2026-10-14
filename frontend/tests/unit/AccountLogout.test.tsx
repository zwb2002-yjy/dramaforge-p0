import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../src/lib/queryKeys";
import { AccountSettingsPage } from "../../src/routes/settings-page";
import {
  ApiError,
  fetchCurrentUser,
  fetchHealth,
  logoutUser,
  setSelectedWorkspaceId,
} from "../../src/lib/api";

vi.mock("../../src/lib/api", async (original) => ({
  ...(await original<typeof import("../../src/lib/api")>()),
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

it("distinguishes a failed account read from a logged-out session", async () => {
  vi.mocked(fetchCurrentUser).mockRejectedValue(new ApiError("服务暂时不可用", 503, "unavailable"));
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AccountSettingsPage />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("无法读取账号");
  expect(screen.queryByText("未登录。", { exact: false })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
});

it("does not display stale identity after the session expires", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(queryKeys.auth.currentUser(), {
    id: "stale-user",
    email: "stale@example.com",
    display_name: "Stale",
  });
  vi.mocked(fetchCurrentUser).mockRejectedValue(new ApiError("登录已过期", 401, "unauthorized"));
  render(
    <QueryClientProvider client={client}>
      <AccountSettingsPage />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("未登录。", { exact: false })).toBeInTheDocument();
  expect(screen.queryByText("stale@example.com")).not.toBeInTheDocument();
});
