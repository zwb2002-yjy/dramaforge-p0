import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProviderConnectionPanel } from "../../src/components/provider/ProviderConnectionPanel";
import * as api from "../../src/lib/api";
import { queryKeys } from "../../src/lib/queryKeys";

vi.mock("../../src/lib/api", () => ({
  bindProjectProvider: vi.fn(),
  createProviderConnection: vi.fn(),
  createProviderModelBinding: vi.fn(),
  listProjectProviderBindings: vi.fn(),
  listProviderConnections: vi.fn(),
  listProviderPlugins: vi.fn(),
  listProviderModelBindings: vi.fn(),
  listProviderProbes: vi.fn(),
  recordProviderQualityEvidence: vi.fn(),
  runProviderProbe: vi.fn(),
  updateProviderConnectionCredential: vi.fn(),
  updateProviderConnection: vi.fn(),
}));

const model: api.ProviderPluginRead["models"][number] = {
  catalog_entry_id: "catalog-image",
  capability_manifest_hash: "hash-image",
  model_id: "exact-image-v2",
  display_name: "Exact Image",
  media_type: "image",
  model_revision: "v2",
  lifecycle: "active",
  catalog_source: "official_static",
  capabilities: ["image.generate"],
  option_schema: {},
};
const plugin: api.ProviderPluginRead = {
  provider_type: "fixture",
  protocol_profile: "fixture-v1",
  display_name: "Fixture Provider",
  default_base_url: "https://fixture.invalid",
  implemented: true,
  paid_capabilities: ["image_t2i"],
  capabilities: ["auth_models", "image_t2i"],
  model_list_path: "/models",
  models: [model],
};
const otherPlugin: api.ProviderPluginRead = {
  ...plugin,
  provider_type: "other",
  display_name: "Other Provider",
  default_base_url: "https://other.invalid",
};
const connection: api.ProviderConnectionRead = {
  id: "connection",
  workspace_id: "workspace",
  provider_type: plugin.provider_type,
  protocol_profile: plugin.protocol_profile,
  display_name: plugin.display_name,
  base_url: "https://saved.invalid",
  enabled: true,
  credential_configured: true,
  credential_key_version: "v1",
  verification_status: "verified",
  verified_at: null,
};
const binding: api.ProviderModelBindingRead = {
  id: "binding",
  connection_id: connection.id,
  media_type: "image",
  purpose: "keyframe",
  model_id: model.model_id,
  enabled: true,
  documented: true,
  contract_tested: true,
  account_verified: true,
  quality_gated: false,
  catalog_entry_id: model.catalog_entry_id,
  capability_manifest_hash: model.capability_manifest_hash,
  remote_resource_kind: "model",
  remote_resource_id: model.model_id,
  invoke_model_value: model.model_id,
};
const probe: api.ProviderProbeRead = {
  probe_id: "probe",
  capability: "auth_models",
  status: "failed",
  evidence_level: "account_verified",
  http_status: 403,
  provider_request_id: null,
  reference_artifact_id: null,
  model_binding_id: null,
  remote_query_kind: null,
  request_fingerprint: "fixture-fingerprint",
  tested_at: "2026-09-19T00:00:00Z",
  error_code: "PROVIDER_AUTH_FAILED",
  discovered_model_ids: [],
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ProviderConnectionPanel workspaceId="workspace" projects={[]} />
    </QueryClientProvider>,
  );
  return client;
}
async function diagnostics() {
  await screen.findByTestId("provider-connection-toggle");
  fireEvent.click(screen.getByTestId("provider-diagnostics-disclosure").querySelector("summary")!);
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.listProviderPlugins).mockResolvedValue([plugin, otherPlugin]);
  vi.mocked(api.listProviderConnections).mockResolvedValue([connection]);
  vi.mocked(api.listProviderModelBindings).mockResolvedValue([]);
  vi.mocked(api.listProviderProbes).mockResolvedValue([]);
  vi.mocked(api.listProjectProviderBindings).mockResolvedValue([]);
});

describe("Provider settings honest state and isolated drafts", () => {
  it("keeps an intentionally blank address and never probes the old address behind a dirty draft", async () => {
    mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("供应商服务地址"), { target: { value: "" } });
    expect(screen.getByLabelText("供应商服务地址")).toHaveValue("");
    expect(screen.getByRole("button", { name: "保存连接地址" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "运行探测" })).toBeDisabled();
    expect(screen.getByText(/不会自动替换成旧地址/)).toBeInTheDocument();
    expect(api.updateProviderConnection).not.toHaveBeenCalled();
    expect(api.runProviderProbe).not.toHaveBeenCalled();
  });

  it("saves only on explicit submission and uses the typed address when creating a connection", async () => {
    vi.mocked(api.listProviderConnections).mockResolvedValue([]);
    vi.mocked(api.createProviderConnection).mockResolvedValue({
      ...connection,
      base_url: "https://custom.invalid",
      verification_status: "unverified",
    });
    mount();
    const key = await screen.findByLabelText("Fixture Provider API Key");
    await waitFor(() => expect(key).toBeEnabled());
    fireEvent.change(screen.getByLabelText("供应商服务地址"), {
      target: { value: "https://custom.invalid" },
    });
    fireEvent.change(key, { target: { value: "synthetic-unit-test-key" } });
    expect(api.createProviderConnection).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存加密 Key" }));
    await waitFor(() =>
      expect(api.createProviderConnection).toHaveBeenCalledWith(
        "workspace",
        "synthetic-unit-test-key",
        {
          provider_type: plugin.provider_type,
          protocol_profile: plugin.protocol_profile,
          display_name: plugin.display_name,
          base_url: "https://custom.invalid",
        },
      ),
    );
    await waitFor(() => expect(screen.getByLabelText("Fixture Provider API Key")).toHaveValue(""));
    expect(api.runProviderProbe).not.toHaveBeenCalled();
  });

  it("does not carry a key, address, probe selection or success message across providers", async () => {
    mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("Fixture Provider API Key"), {
      target: { value: "synthetic-unsaved-key" },
    });
    fireEvent.change(screen.getByLabelText("供应商服务地址"), {
      target: { value: "https://draft.invalid" },
    });
    fireEvent.change(screen.getByLabelText("探测能力"), { target: { value: "image_t2i" } });
    fireEvent.change(screen.getByLabelText("供应商"), { target: { value: "other/fixture-v1" } });
    expect(await screen.findByLabelText("Other Provider API Key")).toHaveValue("");
    expect(screen.getByLabelText("供应商服务地址")).toHaveValue("https://other.invalid");
    expect(screen.queryByTestId("provider-config-message")).not.toBeInTheDocument();
    expect(api.updateProviderConnectionCredential).not.toHaveBeenCalled();
  });

  it("ignores old provider write feedback after switching while the write is pending", async () => {
    let finish!: (value: api.ProviderConnectionRead) => void;
    vi.mocked(api.updateProviderConnection).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("供应商服务地址"), {
      target: { value: "https://new.invalid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存连接地址" }));
    await waitFor(() => expect(api.updateProviderConnection).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("供应商"), { target: { value: "other/fixture-v1" } });
    fireEvent.change(await screen.findByLabelText("Other Provider API Key"), {
      target: { value: "synthetic-other-draft" },
    });
    await act(async () => {
      finish({ ...connection, base_url: "https://new.invalid" });
    });
    expect(screen.getByLabelText("Other Provider API Key")).toHaveValue("synthetic-other-draft");
    expect(screen.queryByTestId("provider-config-message")).not.toBeInTheDocument();
  });

  it("keeps failed saves as drafts without showing raw server errors or blindly retrying", async () => {
    vi.mocked(api.updateProviderConnection).mockRejectedValue(
      new Error("internal-sensitive-response"),
    );
    mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("供应商服务地址"), {
      target: { value: "https://draft.invalid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存连接地址" }));
    expect(await screen.findByTestId("provider-config-message")).toHaveAttribute("role", "alert");
    expect(screen.getByLabelText("供应商服务地址")).toHaveValue("https://draft.invalid");
    expect(screen.queryByText("internal-sensitive-response")).not.toBeInTheDocument();
    expect(api.updateProviderConnection).toHaveBeenCalledTimes(1);
  });

  it("does not misreport failed evidence/binding reads as an empty setup", async () => {
    vi.mocked(api.listProviderProbes).mockRejectedValue(new Error("offline"));
    vi.mocked(api.listProviderModelBindings).mockRejectedValue(new Error("offline"));
    mount();
    await diagnostics();
    expect(await screen.findByText(/能力证据读取失败/)).toBeInTheDocument();
    expect(screen.getByText(/模型绑定读取失败/)).toBeInTheDocument();
    expect(screen.queryByText("暂无能力证据。")).not.toBeInTheDocument();
    expect(screen.queryByText(/^尚无模型绑定/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加关键帧模型绑定" })).toBeDisabled();
  });

  it("blocks disabled connections and paid probes without treating checkbox consent as budget authorization", async () => {
    const client = mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("探测能力"), { target: { value: "image_t2i" } });
    expect(screen.getByText(/当前接口不能提交单次正数预算/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "付费探测暂不可用" })).toBeDisabled();
    act(() =>
      client.setQueryData(queryKeys.provider.connections("workspace"), [
        { ...connection, enabled: false },
      ]),
    );
    expect(await screen.findByTestId("provider-connection-disabled-note")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("探测能力"), { target: { value: "auth_models" } });
    expect(screen.getByRole("button", { name: "运行探测" })).toBeDisabled();
    expect(api.runProviderProbe).not.toHaveBeenCalled();
  });

  it("blocks generation probes even if the plugin omits their paid classification", async () => {
    vi.mocked(api.listProviderPlugins).mockResolvedValue([{ ...plugin, paid_capabilities: [] }]);
    mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("探测能力"), { target: { value: "image_t2i" } });
    expect(screen.getByRole("button", { name: "付费探测暂不可用" })).toBeDisabled();
    expect(screen.getByText(/当前接口不能提交单次正数预算/)).toBeInTheDocument();
    expect(api.runProviderProbe).not.toHaveBeenCalled();
  });

  it("treats an HTTP-successful failed probe result as failure and re-reads connection verification", async () => {
    vi.mocked(api.runProviderProbe).mockResolvedValue(probe);
    mount();
    await diagnostics();
    await waitFor(() => expect(screen.getByRole("button", { name: "运行探测" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "运行探测" }));
    expect(await screen.findByTestId("provider-config-message")).toHaveClass("err");
    expect(screen.getByTestId("provider-config-message")).toHaveTextContent("本次检查失败");
    await waitFor(() =>
      expect(vi.mocked(api.listProviderConnections).mock.calls.length).toBeGreaterThan(1),
    );
    expect(api.runProviderProbe).toHaveBeenCalledTimes(1);
  });

  it("blocks bindings when the current revision is rejected even with historical successful evidence", async () => {
    vi.mocked(api.listProviderProbes).mockResolvedValue([
      { ...probe, status: "passed", http_status: 200, error_code: null },
    ]);
    const client = mount();
    await diagnostics();
    await waitFor(() => expect(screen.getByLabelText("关键帧模型")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("关键帧模型"), { target: { value: model.model_id } });
    expect(screen.getByRole("button", { name: "添加关键帧模型绑定" })).toBeEnabled();
    act(() =>
      client.setQueryData(queryKeys.provider.connections("workspace"), [
        { ...connection, verification_status: "failed" },
      ]),
    );
    await waitFor(() =>
      expect(screen.getByTestId("provider-connection-status")).toHaveTextContent("当前认证被拒绝"),
    );
    expect(screen.getByRole("button", { name: "添加关键帧模型绑定" })).toBeDisabled();
    expect(api.runProviderProbe).not.toHaveBeenCalled();
  });

  it("does not let a late historical auth failure override the backend's current verified revision", async () => {
    const client = mount();
    await diagnostics();
    await waitFor(() => expect(screen.getByLabelText("关键帧模型")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("关键帧模型"), { target: { value: model.model_id } });
    expect(screen.getByRole("button", { name: "添加关键帧模型绑定" })).toBeEnabled();
    act(() => client.setQueryData(queryKeys.provider.probes("workspace", connection.id), [probe]));
    // The failure remains visible evidence, but carries no current-revision authority.
    expect(await screen.findByText(/错误代码：PROVIDER_AUTH_FAILED/)).toBeInTheDocument();
    expect(screen.getByTestId("provider-connection-status")).toHaveTextContent("曾通过认证");
    expect(screen.getByTestId("provider-connection-status")).not.toHaveTextContent("认证被拒绝");
    expect(screen.getByRole("button", { name: "添加关键帧模型绑定" })).toBeEnabled();
    expect(api.runProviderProbe).not.toHaveBeenCalled();
  });

  it("allows another catalog model to be chosen but does not write on select", async () => {
    vi.mocked(api.listProviderModelBindings).mockResolvedValue([binding]);
    const secondModel = {
      ...model,
      catalog_entry_id: "catalog-image-3",
      capability_manifest_hash: "hash-3",
      model_id: "exact-image-v3",
    };
    vi.mocked(api.listProviderPlugins).mockResolvedValue([
      { ...plugin, models: [model, secondModel] },
    ]);
    vi.mocked(api.createProviderModelBinding).mockResolvedValue({
      ...binding,
      id: "new-binding",
      model_id: secondModel.model_id,
    });
    mount();
    await diagnostics();
    await waitFor(() => expect(screen.getByLabelText("关键帧模型")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("关键帧模型"), {
      target: { value: secondModel.model_id },
    });
    expect(api.createProviderModelBinding).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "添加关键帧模型绑定" }));
    await waitFor(() =>
      expect(api.createProviderModelBinding).toHaveBeenCalledWith("workspace", connection.id, {
        media_type: "image",
        purpose: "keyframe",
        model_id: secondModel.model_id,
        capability_contract_id: secondModel.catalog_entry_id,
      }),
    );
  });

  it("lets the user bind a discovered model to an installed capability plugin contract", async () => {
    const supported = {
      ...model,
      catalog_entry_id: "catalog-supported",
      capability_manifest_hash: "hash-supported",
      model_id: "remote-supported",
    };
    const catalogOnly = {
      ...model,
      catalog_entry_id: "catalog-not-on-account",
      capability_manifest_hash: "hash-not-on-account",
      model_id: "catalog-only",
    };
    vi.mocked(api.listProviderPlugins).mockResolvedValue([
      { ...plugin, models: [supported, catalogOnly] },
    ]);
    vi.mocked(api.listProviderProbes).mockResolvedValue([
      {
        ...probe,
        status: "passed",
        http_status: 200,
        error_code: null,
        discovered_model_ids: ["remote-supported", "remote-unknown"],
      },
    ]);

    mount();
    await diagnostics();

    await waitFor(() => expect(screen.getByLabelText("关键帧模型")).toBeEnabled());
    const imagePicker = screen.getByLabelText("关键帧模型");
    expect(within(imagePicker).getByRole("option", { name: /remote-supported/ })).toBeInTheDocument();
    expect(within(imagePicker).getByRole("option", { name: /remote-unknown/ })).toBeInTheDocument();
    expect(within(imagePicker).queryByRole("option", { name: /catalog-only/ })).not.toBeInTheDocument();
    expect(screen.getByTestId("provider-discovered-models")).toHaveTextContent("remote-unknown");
    expect(screen.getByTestId("provider-discovered-models")).toHaveTextContent("尚未匹配能力插件");
    fireEvent.change(screen.getByLabelText("关键帧模型"), {
      target: { value: "remote-unknown" },
    });
    fireEvent.change(screen.getByLabelText("关键帧能力插件"), {
      target: { value: supported.catalog_entry_id },
    });
    vi.mocked(api.createProviderModelBinding).mockResolvedValue({
      ...binding,
      model_id: "remote-unknown",
      catalog_entry_id: supported.catalog_entry_id,
    });
    fireEvent.click(screen.getByRole("button", { name: "添加关键帧模型绑定" }));
    await waitFor(() =>
      expect(api.createProviderModelBinding).toHaveBeenCalledWith("workspace", connection.id, {
        media_type: "image",
        purpose: "keyframe",
        model_id: "remote-unknown",
        capability_contract_id: supported.catalog_entry_id,
      }),
    );
  });

  it("requires the exact explicit binding for a non-generating remote-task query instead of taking the first model", async () => {
    const videos = ["one", "two"].map((id) => ({
      ...model,
      media_type: "video",
      model_id: `video-${id}`,
      catalog_entry_id: `catalog-${id}`,
      capability_manifest_hash: `hash-${id}`,
    }));
    vi.mocked(api.listProviderPlugins).mockResolvedValue([
      { ...plugin, capabilities: ["auth_models", "video_poll_download"], models: videos },
    ]);
    vi.mocked(api.listProviderModelBindings).mockResolvedValue(
      videos.map((item) => ({
        ...binding,
        id: item.model_id,
        media_type: "video",
        purpose: "video",
        model_id: item.model_id,
        catalog_entry_id: item.catalog_entry_id,
        capability_manifest_hash: item.capability_manifest_hash,
      })),
    );
    vi.mocked(api.runProviderProbe).mockResolvedValue({
      ...probe,
      capability: "video_poll_download",
      status: "passed",
    });
    mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("探测能力"), {
      target: { value: "video_poll_download" },
    });
    expect(screen.getByLabelText("探测模型绑定")).toHaveValue("");
    expect(screen.getByRole("button", { name: "运行探测" })).toBeDisabled();
    await waitFor(() => expect(screen.getByLabelText("探测模型绑定")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("探测模型绑定"), { target: { value: "video-two" } });
    fireEvent.change(screen.getByLabelText("远端任务 ID"), {
      target: { value: "synthetic-task-id" },
    });
    fireEvent.click(screen.getByRole("button", { name: "运行探测" }));
    await waitFor(() =>
      expect(api.runProviderProbe).toHaveBeenCalledWith("workspace", "connection", {
        capability: "video_poll_download",
        model_binding_id: "video-two",
        remote_task_id: "synthetic-task-id",
        remote_query_kind: "video_id",
        paid_request_confirmed: false,
      }),
    );
  });

  it("pins the initial catalog choice so a background reorder does not change the provider", async () => {
    const client = mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("供应商服务地址"), {
      target: { value: "https://local-draft.invalid" },
    });
    act(() => client.setQueryData(queryKeys.provider.plugins(), [otherPlugin, plugin]));
    await waitFor(() =>
      expect(screen.getByLabelText("供应商").querySelector("option")).toHaveTextContent(
        "Other Provider",
      ),
    );
    expect(screen.getByLabelText("供应商")).toHaveValue("fixture/fixture-v1");
    expect(screen.getByLabelText("供应商服务地址")).toHaveValue("https://local-draft.invalid");
  });

  it("never silently changes an explicit provider choice when the catalog refresh removes it", async () => {
    const client = mount();
    await diagnostics();
    fireEvent.change(screen.getByLabelText("供应商"), { target: { value: "other/fixture-v1" } });
    act(() => client.setQueryData(queryKeys.provider.plugins(), [plugin]));
    expect(client.getQueryData(queryKeys.provider.plugins())).toEqual([plugin]);
    // Query cache writes are synchronous; its React observer notification is not.
    expect(await screen.findByText(/所选插件已不在目录中/)).toBeInTheDocument();
    expect(screen.getByLabelText("供应商")).toHaveValue("other/fixture-v1");
    expect(screen.queryByLabelText("Other Provider API Key")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Fixture Provider API Key")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("供应商服务地址")).not.toBeInTheDocument();
    expect(api.runProviderProbe).not.toHaveBeenCalled();
  });
});
