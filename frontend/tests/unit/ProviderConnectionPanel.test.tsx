import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProviderConnectionPanel } from "../../src/components/provider/ProviderConnectionPanel";
import {
  listProviderConnections,
  listProviderModelBindings,
  listProviderPlugins,
  listProviderProbes,
} from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({
  bindProjectProvider: vi.fn(),
  createProviderConnection: vi.fn(),
  createProviderModelBinding: vi.fn(),
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

describe("Provider connection contract revisions", () => {
  it("does not misreport a failed workspace query as an unconfigured provider", async () => {
    vi.mocked(listProviderConnections).mockRejectedValue(new Error("workspace context mismatch"));
    vi.mocked(listProviderPlugins).mockResolvedValue([]);

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ProviderConnectionPanel workspaceId="workspace-2" projects={[]} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("读取失败")).toBeInTheDocument();
    expect(screen.getByText("连接列表加载失败：workspace context mismatch")).toBeInTheDocument();
  });

  it("keeps historical bindings visible but only allows the active revision on new projects", async () => {
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
    expect(
      within(activeRow as HTMLElement).getByRole("button", { name: "绑定所选项目" }),
    ).toBeEnabled();
  });
});
