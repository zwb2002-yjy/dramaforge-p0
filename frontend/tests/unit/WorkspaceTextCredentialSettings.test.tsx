import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceTextCredentialSettings } from "../../src/components/provider/WorkspaceTextCredentialSettings";
import { getWorkspaceCredentialStatus, putWorkspaceCredential } from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({
  getWorkspaceCredentialStatus: vi.fn(),
  putWorkspaceCredential: vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

describe("Workspace text credential settings", () => {
  it("shows status and saves a new text credential without echoing it", async () => {
    vi.mocked(getWorkspaceCredentialStatus).mockResolvedValue({
      provider: "text",
      configured: false,
      key_version: null,
    });
    vi.mocked(putWorkspaceCredential).mockResolvedValue({
      provider: "text",
      configured: true,
      key_version: "v2",
    });
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <WorkspaceTextCredentialSettings workspaceId="workspace-1" />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("未配置")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("文本模型 API Key"), {
      target: { value: "text-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存凭证" }));

    await waitFor(() =>
      expect(putWorkspaceCredential).toHaveBeenCalledWith("workspace-1", "text", "text-secret"),
    );
    expect(
      await screen.findByText("文本模型凭证已加密保存，本界面不会回读 Key。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("text-secret")).not.toBeInTheDocument();
  });
});
