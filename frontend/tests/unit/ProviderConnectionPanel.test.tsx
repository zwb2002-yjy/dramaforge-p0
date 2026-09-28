import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProviderConnectionPanel } from "../../src/components/provider/ProviderConnectionPanel";
import {
  listProjectProviderBindings,
  listProviderConnections,
  listProviderModelBindings,
  listProviderPlugins,
  listProviderProbes,
  updateProviderConnection,
} from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({
  bindProjectProvider: vi.fn(),
  createProviderConnection: vi.fn(),
  createProviderModelBinding: vi.fn(),
  listProjectProviderBindings: vi.fn(),
  listProviderConnections: vi.fn(),
  listProviderModelBindings: vi.fn(),
  listProviderPlugins: vi.fn(),
  listProviderProbes: vi.fn(),
  recordProviderQualityEvidence: vi.fn(),
  runProviderProbe: vi.fn(),
  setProviderModelBindingPricing: vi.fn(),
  updateProviderConnection: vi.fn(),
  updateProviderConnectionCredential: vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

/** The panel resolves the active connection through the selected plugin. */
const AGNES_PLUGIN = {
  provider_type: "agnes",
  protocol_profile: "agnes_cn_v1",
  display_name: "Agnes China",
  default_base_url: "https://api.agnes-ai.cn",
  implemented: true,
  paid_capabilities: ["image_i2i"],
  capabilities: ["auth_models", "image_i2i"],
  model_list_path: "/v1/models",
  models: [],
} as never;

describe("Provider connection contract revisions", () => {
  it("does not misreport a failed workspace query as an unconfigured provider", async () => {
    vi.mocked(listProviderConnections).mockRejectedValue(new Error("workspace context mismatch"));
    vi.mocked(listProviderPlugins).mockResolvedValue([AGNES_PLUGIN]);

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ProviderConnectionPanel workspaceId="workspace-2" projects={[]} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("读取失败")).toBeInTheDocument();
    expect(screen.getByText("连接列表加载失败；状态未知，不能当作未配置。")).toBeInTheDocument();
  });

  it("keeps historical bindings visible but only allows the active revision on new projects", async () => {
    vi.mocked(listProjectProviderBindings).mockResolvedValue([]);
    vi.mocked(listProviderConnections).mockResolvedValue([
      {
        id: "connection-1",
        workspace_id: "workspace-1",
        provider_type: "agnes",
        display_name: "Agnes China",
        base_url: "https://api.agnes-ai.cn",
        protocol_profile: "agnes_cn_v1",
        enabled: true,
        credential_configured: true,
        credential_key_version: "v1",
        verification_status: "verified",
        verified_at: null,
      },
    ]);
    vi.mocked(listProviderPlugins).mockResolvedValue([
      {
        provider_type: "agnes",
        protocol_profile: "agnes_cn_v1",
        display_name: "Agnes China",
        default_base_url: "https://api.agnes-ai.cn",
        implemented: true,
        paid_capabilities: ["image_i2i"],
        capabilities: ["auth_models", "image_i2i"],
        model_list_path: "/v1/models",
        models: [
          {
            catalog_entry_id: "catalog-v2",
            capability_manifest_hash: "hash-v2",
            model_id: "agnes-image-2.1-flash",
            display_name: "Agnes Image Flash",
            media_type: "image",
            model_revision: "v2",
            lifecycle: "active",
            catalog_source: "official_static",
            capabilities: ["image.t2i", "image.i2i"],
            option_schema: {},
          },
        ],
      },
    ]);
    vi.mocked(listProviderProbes).mockResolvedValue([]);
    vi.mocked(listProviderModelBindings).mockResolvedValue([
      {
        id: "binding-v1",
        connection_id: "connection-1",
        media_type: "image",
        model_id: "agnes-image-2.1-flash",
        purpose: "keyframe",
        enabled: true,
        documented: true,
        contract_tested: true,
        account_verified: true,
        quality_gated: true,
        catalog_entry_id: "catalog-v1",
        capability_manifest_hash: "hash-v1",
        remote_resource_kind: "model",
        remote_resource_id: "agnes-image-2.1-flash",
        invoke_model_value: "agnes-image-2.1-flash",
        pricing_snapshot: {},
      },
      {
        id: "binding-v2",
        connection_id: "connection-1",
        media_type: "image",
        model_id: "agnes-image-2.1-flash",
        purpose: "keyframe",
        enabled: true,
        documented: true,
        contract_tested: true,
        account_verified: true,
        quality_gated: false,
        catalog_entry_id: "catalog-v2",
        capability_manifest_hash: "hash-v2",
        remote_resource_kind: "model",
        remote_resource_id: "agnes-image-2.1-flash",
        invoke_model_value: "agnes-image-2.1-flash",
        pricing_snapshot: {},
      },
    ]);

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ProviderConnectionPanel
          workspaceId="workspace-1"
          projects={[
            {
              id: "project-1",
              workspace_id: "workspace-1",
              name: "Portrait short",
              stage: "planning",
              aspect_ratio: "9:16",
              target_platform: "other",
              provider_dispatch_frozen: false,
              version: 1,
              creative_profile: {
                id: "profile-1",
                project_id: "project-1",
                start_type: "FREE",
                created_from_template_key: null,
                template_version: null,
                template_contract_hash: null,
                director_autonomy: "ASSIST",
                selected_genre: null,
                selected_style_ids: [],
                selected_skill_ids: [],
                selected_shot_language: null,
                asset_slot_requirements: {},
                strategy_snapshot: {},
                version: 1,
              },
            },
          ]}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(
      (await screen.findByTestId("provider-diagnostics-disclosure")).querySelector("summary")!,
    );
    expect(await screen.findByText("keyframe · 历史合同")).toBeInTheDocument();
    expect(screen.getByText("keyframe · v2")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("项目 Provider 绑定"), {
      target: { value: "project-1" },
    });

    const historicalRow = screen.getByText("keyframe · 历史合同").closest(".provider-binding");
    const activeRow = screen.getByText("keyframe · v2").closest(".provider-binding");
    expect(historicalRow).not.toBeNull();
    expect(activeRow).not.toBeNull();
    expect(
      within(historicalRow as HTMLElement).getByRole("button", { name: "绑定所选项目" }),
    ).toBeDisabled();
    await vi.waitFor(() =>
      expect(
        within(activeRow as HTMLElement).getByRole("button", { name: "绑定所选项目" }),
      ).toBeEnabled(),
    );
  });

  it("enables and disables the connection from the settings surface", async () => {
    vi.mocked(listProviderConnections).mockResolvedValue([
      {
        id: "connection-1",
        workspace_id: "workspace-1",
        provider_type: "agnes",
        display_name: "Agnes China",
        base_url: "https://api.agnes-ai.cn",
        protocol_profile: "agnes_cn_v1",
        enabled: true,
        credential_configured: true,
        credential_key_version: "v1",
        verification_status: "verified",
        verified_at: null,
      },
    ]);
    vi.mocked(listProviderPlugins).mockResolvedValue([AGNES_PLUGIN]);
    vi.mocked(listProviderProbes).mockResolvedValue([]);
    vi.mocked(listProviderModelBindings).mockResolvedValue([]);
    vi.mocked(updateProviderConnection).mockResolvedValue({} as never);

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ProviderConnectionPanel workspaceId="workspace-1" projects={[]} />
      </QueryClientProvider>,
    );

    const toggle = await screen.findByTestId("provider-connection-toggle");
    expect(toggle).toHaveTextContent("停用连接");
    fireEvent.click(toggle);
    await vi.waitFor(() =>
      expect(updateProviderConnection).toHaveBeenCalledWith("workspace-1", "connection-1", {
        enabled: false,
      }),
    );
  });

  it("reads the project's current keyframe/video binding back after a refresh", async () => {
    vi.mocked(listProviderConnections).mockResolvedValue([
      {
        id: "connection-1",
        workspace_id: "workspace-1",
        provider_type: "agnes",
        display_name: "Agnes China",
        base_url: "https://api.agnes-ai.cn",
        protocol_profile: "agnes_cn_v1",
        enabled: true,
        credential_configured: true,
        credential_key_version: "v1",
        verification_status: "verified",
        verified_at: null,
      },
    ]);
    vi.mocked(listProviderPlugins).mockResolvedValue([AGNES_PLUGIN]);
    vi.mocked(listProviderProbes).mockResolvedValue([]);
    vi.mocked(listProviderModelBindings).mockResolvedValue([]);
    vi.mocked(listProjectProviderBindings).mockResolvedValue([
      {
        id: "project-binding-1",
        project_id: "project-1",
        purpose: "keyframe",
        model_binding_id: "binding-v2",
        selection_strategy: "explicit_binding",
        fallback_policy: "none",
        model_id: "agnes-image-2.1-flash",
        display_name: "Agnes Image Flash",
        provider_type: "agnes",
        model_binding_enabled: true,
      },
    ]);

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ProviderConnectionPanel
          workspaceId="workspace-1"
          projects={[
            {
              id: "project-1",
              workspace_id: "workspace-1",
              name: "Portrait short",
              stage: "planning",
              aspect_ratio: "9:16",
              target_platform: "other",
              provider_dispatch_frozen: false,
              version: 1,
              creative_profile: {
                id: "profile-1",
                project_id: "project-1",
                start_type: "FREE",
                created_from_template_key: null,
                template_version: null,
                template_contract_hash: null,
                director_autonomy: "ASSIST",
                selected_genre: null,
                selected_style_ids: [],
                selected_skill_ids: [],
                selected_shot_language: null,
                asset_slot_requirements: {},
                strategy_snapshot: {},
                version: 1,
              },
            },
          ]}
        />
      </QueryClientProvider>,
    );

    await screen.findByTestId("provider-connection-toggle");
    fireEvent.click(
      screen.getByTestId("provider-diagnostics-disclosure").querySelector("summary")!,
    );
    fireEvent.change(screen.getByLabelText("项目 Provider 绑定"), {
      target: { value: "project-1" },
    });

    const rows = await screen.findByTestId("project-provider-bindings");
    // The model identity, not a raw binding id, is what the Owner needs to see.
    await vi.waitFor(() => expect(rows).toHaveTextContent("关键帧：Agnes Image Flash（agnes）"));
    expect(rows).not.toHaveTextContent("binding-v2");
  });
});
