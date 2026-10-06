import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TextGatewaySettings } from "../../src/components/provider/TextGatewaySettings";
import * as api from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({
  createProviderConnection: vi.fn(),
  listProviderConnections: vi.fn(),
  listProviderProbes: vi.fn(),
  runProviderProbe: vi.fn(),
  updateProviderConnection: vi.fn(),
  updateProviderConnectionCredential: vi.fn(),
}));

function mount() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TextGatewaySettings workspaceId="workspace" />
    </QueryClientProvider>,
  );
}

describe("TextGatewaySettings", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.listProviderConnections).mockResolvedValue([]);
    vi.mocked(api.listProviderProbes).mockResolvedValue([]);
  });

  it("edits and saves a workspace text gateway URL and encrypted key", async () => {
    vi.mocked(api.createProviderConnection).mockResolvedValue({
      id: "text-connection",
      workspace_id: "workspace",
      provider_type: "litellm",
      protocol_profile: "openai_chat_v1",
      display_name: "Text",
      base_url: "https://gateway.example/v1",
      enabled: true,
      credential_configured: true,
      credential_key_version: "1:test",
      verification_status: "unverified",
      verified_at: null,
    });
    mount();
    const url = await screen.findByLabelText("文本服务 URL");
    fireEvent.change(url, { target: { value: "https://gateway.example/v1" } });
    fireEvent.change(screen.getByLabelText("文本服务 API Key"), {
      target: { value: "secret-test-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存文本连接" }));
    await waitFor(() =>
      expect(api.createProviderConnection).toHaveBeenCalledWith("workspace", "secret-test-key", {
        provider_type: "litellm",
        protocol_profile: "openai_chat_v1",
        display_name: "LiteLLM / OpenAI 兼容文本服务",
        base_url: "https://gateway.example/v1",
      }),
    );
  });

  it("shows models returned by explicit discovery", async () => {
    vi.mocked(api.listProviderConnections).mockResolvedValue([
      {
        id: "text-connection",
        workspace_id: "workspace",
        provider_type: "litellm",
        protocol_profile: "openai_chat_v1",
        display_name: "Text",
        base_url: "https://gateway.example/v1",
        enabled: true,
        credential_configured: true,
        credential_key_version: "1:test",
        verification_status: "verified",
        verified_at: null,
      },
    ]);
    vi.mocked(api.runProviderProbe).mockResolvedValue({
      probe_id: "probe",
      capability: "auth_models",
      status: "passed",
      evidence_level: "account_verified",
      http_status: 200,
      provider_request_id: null,
      reference_artifact_id: null,
      model_binding_id: null,
      remote_query_kind: null,
      request_fingerprint: "fingerprint",
      tested_at: "2026-09-21T00:00:00Z",
      error_code: null,
      discovered_model_ids: ["agnes-2.5-flash"],
    });
    mount();
    await waitFor(() => expect(screen.getByRole("button", { name: "探测文本模型" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "探测文本模型" }));
    expect(await screen.findByText(/已发现 1 个文本模型/)).toBeInTheDocument();
  });
});
