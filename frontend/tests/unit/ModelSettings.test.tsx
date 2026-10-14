import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddProviderDialog } from "../../src/components/provider/AddProviderDialog";
import { useModelActivation } from "../../src/components/provider/useModelActivation";
import type { WorkspaceModelRole } from "../../src/lib/workspaceModelRoles";
import { ProviderList } from "../../src/components/provider/ProviderList";
import { ProviderDetails } from "../../src/components/provider/ProviderDetails";
import type { ProviderPluginRead } from "../../src/lib/api";

const WS = "11111111-1111-4111-8111-111111111111";
const CONN = "22222222-2222-4222-8222-222222222222";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function contract(
  id: string,
  model_id: string,
  media_type: "image" | "video",
  display_name: string,
): ProviderPluginRead["models"][number] {
  return {
    catalog_entry_id: id,
    capability_manifest_hash: "h".repeat(64),
    model_id,
    display_name,
    media_type,
    model_revision: "2026-01-01",
    lifecycle: "active",
    implementation_status: "contract_tested",
    catalog_source: "official_static",
    capabilities: [],
    option_schema: {},
    capability_summary: {} as ProviderPluginRead["models"][number]["capability_summary"],
  } as ProviderPluginRead["models"][number];
}

const MEDIA_PLUGIN: ProviderPluginRead = {
  provider_type: "volcengine",
  protocol_profile: "ark_cn_v1",
  display_name: "火山方舟",
  default_base_url: "https://ark.example.test",
  kind: "media",
  implemented: true,
  paid_capabilities: ["image_t2i"],
  capabilities: ["auth_models"],
  model_list_path: "/models",
  models: [
    contract("c-image", "seedream-4", "image", "Seedream 4"),
    contract("c-video", "seedance-2", "video", "Seedance 2"),
  ],
};

const COMPAT_PLUGIN: ProviderPluginRead = {
  ...MEDIA_PLUGIN,
  provider_type: "openai_compatible_media",
  protocol_profile: "openai_media_v1",
  display_name: "OpenAI 兼容图像 / 视频",
  models: [contract("c-generic", "@contract/openai-video-v1", "video", "OpenAI 视频协议")],
};

const TEXT_PLUGIN: ProviderPluginRead = {
  ...MEDIA_PLUGIN,
  provider_type: "litellm",
  protocol_profile: "openai_chat_v1",
  display_name: "LiteLLM / OpenAI 兼容文本服务",
  default_base_url: "http://litellm:4000",
  kind: "text",
  models: [],
};

function connection(overrides: Record<string, unknown> = {}) {
  return {
    id: CONN,
    workspace_id: WS,
    provider_type: "volcengine",
    display_name: "火山方舟",
    base_url: "https://ark.example.test",
    protocol_profile: "ark_cn_v1",
    enabled: true,
    credential_configured: true,
    credential_key_version: "v1",
    verification_status: "unverified",
    verified_at: null,
    connection_revision_id: "revision-1",
    ...overrides,
  };
}

function probe(status: "passed" | "failed", ids: string[], http_status = 200) {
  return {
    probe_id: "p1",
    capability: "auth_models",
    status,
    evidence_level: "account_verified",
    http_status,
    provider_request_id: null,
    reference_artifact_id: null,
    model_binding_id: null,
    remote_query_kind: null,
    request_fingerprint: "f".repeat(64),
    tested_at: "2026-10-07T00:00:00Z",
    error_code: status === "failed" ? "AUTH_REJECTED" : null,
    discovered_model_ids: ids,
    connection_revision_id: "revision-1",
  };
}

function wrap(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

type Call = { method: string; url: string; body: unknown };

function mockApi(handler: (call: Call) => Promise<Response> | undefined) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const call = {
      method: init?.method ?? "GET",
      url,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf" });
    return handler(call) ?? json([]);
  });
  return calls;
}

async function connectWith(plugins: ProviderPluginRead[], key = "sk-test") {
  wrap(<AddProviderDialog workspaceId={WS} plugins={plugins} onClose={() => undefined} />);
  const dialog = await screen.findByRole("dialog", { name: "添加供应商" });
  fireEvent.change(within(dialog).getByLabelText("API Key"), { target: { value: key } });
  fireEvent.click(within(dialog).getByRole("button", { name: "连接并读取模型" }));
  return dialog;
}

describe("AddProviderDialog", () => {
  afterEach(() => vi.restoreAllMocks());

  it("adds a local service as custom without a vendor category selector", async () => {
    mockApi(() => undefined);
    wrap(
      <AddProviderDialog
        workspaceId={WS}
        custom
        plugins={[COMPAT_PLUGIN]}
        onClose={() => undefined}
      />,
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("navigation")).toBeNull();
    expect(within(dialog).getByLabelText("连接名称")).toHaveValue("");
    expect(within(dialog).getByLabelText("服务地址")).toHaveValue("");
    fireEvent.change(within(dialog).getByLabelText("连接名称"), { target: { value: "本地部署" } });
    fireEvent.change(within(dialog).getByLabelText("服务地址"), {
      target: { value: "http://172.18.6.80:30020/v1" },
    });
    fireEvent.change(within(dialog).getByLabelText("API Key"), {
      target: { value: "test-local-key" },
    });
    expect(within(dialog).getByRole("button", { name: "连接并读取模型" })).toBeEnabled();
  });

  it("connects, reads the catalog and binds only the ticked exact contracts", async () => {
    const calls = mockApi(({ method, url }) => {
      if (method === "POST" && url.endsWith("/provider-connections"))
        return json(connection(), 201);
      if (method === "POST" && url.endsWith("/probes"))
        return json(probe("passed", ["seedream-4", "seedance-2", "mystery-x"]));
      if (method === "POST" && url.endsWith("/model-bindings"))
        return json({ id: "b1", model_id: "seedream-4" }, 201);
      return undefined;
    });
    await connectWith([MEDIA_PLUGIN]);

    const picker = await screen.findByTestId("provider-model-picker");
    expect(within(picker).getByText("seedream-4")).toBeVisible();
    expect(within(picker).getByText("seedance-2")).toBeVisible();
    // Unknown ids are listed but never bound by name guessing.
    expect(within(picker).getByText("已发现 · 暂未支持执行 1")).toBeInTheDocument();
    fireEvent.click(within(picker).getByRole("checkbox", { name: /seedream-4/ }));
    fireEvent.click(screen.getByRole("button", { name: "添加 1 个模型" }));

    await waitFor(() =>
      expect(calls.filter((call) => call.url.endsWith("/model-bindings"))).toHaveLength(1),
    );
    const create = calls.find(
      (call) => call.method === "POST" && call.url.endsWith("/provider-connections"),
    );
    expect(create?.body).toMatchObject({
      provider_type: "volcengine",
      protocol_profile: "ark_cn_v1",
      display_name: "Seedance",
      base_url: "https://ark.example.test",
      api_key: "sk-test",
    });
    expect(calls.find((call) => call.url.endsWith("/probes"))?.body).toEqual({
      capability: "auth_models",
    });
    expect(calls.find((call) => call.url.endsWith("/model-bindings"))?.body).toMatchObject({
      media_type: "image",
      model_id: "seedream-4",
      purpose: "keyframe",
      capability_contract_id: "c-image",
    });
    // Setup never requests a generation probe.
    expect(calls.some((call) => /image_t2i|video_i2v/.test(JSON.stringify(call.body)))).toBe(false);
  });

  it.each([
    [401, "Key 无效或没有权限"],
    [403, "Key 无效或没有权限"],
    [404, "没有模型目录接口"],
    [503, "暂时不可用"],
  ])("explains a %s catalog failure and keeps the dialog editable", async (status, text) => {
    mockApi(({ method, url }) => {
      if (method === "POST" && url.endsWith("/provider-connections"))
        return json(connection(), 201);
      if (method === "POST" && url.endsWith("/probes")) return json(probe("failed", [], status));
      return undefined;
    });
    const dialog = await connectWith([MEDIA_PLUGIN]);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(text);
    expect(within(dialog).getByLabelText("API Key")).toHaveAttribute(
      "placeholder",
      "已保存，留空不更换",
    );
  });

  it("reports a network failure without pretending the connection works", async () => {
    mockApi(({ method, url }) => {
      if (method === "POST" && url.endsWith("/provider-connections"))
        return json(connection(), 201);
      if (method === "POST" && url.endsWith("/probes"))
        return Promise.reject(new TypeError("Failed to fetch"));
      return undefined;
    });
    const dialog = await connectWith([MEDIA_PLUGIN]);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Failed to fetch");
    expect(within(dialog).getByRole("button", { name: "连接并读取模型" })).toBeEnabled();
  });

  it("offers catalog models when the account returns an empty catalog", async () => {
    mockApi(({ method, url }) => {
      if (method === "POST" && url.endsWith("/provider-connections"))
        return json(connection(), 201);
      if (method === "POST" && url.endsWith("/probes")) return json(probe("passed", []));
      return undefined;
    });
    await connectWith([MEDIA_PLUGIN]);
    const picker = await screen.findByTestId("provider-model-picker");
    expect(within(picker).getAllByRole("checkbox")).toHaveLength(2);
  });

  it("requires an explicit protocol choice before an unknown id can be bound", async () => {
    const calls = mockApi(({ method, url }) => {
      if (method === "POST" && url.endsWith("/provider-connections"))
        return json(connection({ provider_type: "openai_compatible_media" }), 201);
      if (method === "POST" && url.endsWith("/probes")) return json(probe("passed", ["h3-local"]));
      if (method === "POST" && url.endsWith("/model-bindings")) return json({ id: "b1" }, 201);
      return undefined;
    });
    await connectWith([COMPAT_PLUGIN]);
    const picker = await screen.findByTestId("provider-model-picker");
    const check = within(picker).getByRole("checkbox", { name: "使用 h3-local" });
    expect(check).toBeDisabled();
    fireEvent.change(within(picker).getByLabelText("h3-local 调用方式"), {
      target: { value: "c-generic" },
    });
    fireEvent.click(within(picker).getByRole("checkbox", { name: "使用 h3-local" }));
    fireEvent.click(screen.getByRole("button", { name: "添加 1 个模型" }));
    await waitFor(() =>
      expect(calls.find((call) => call.url.endsWith("/model-bindings"))?.body).toMatchObject({
        media_type: "video",
        model_id: "h3-local",
        purpose: "video",
        capability_contract_id: "c-generic",
      }),
    );
  });

  it("reports partial binding success honestly", async () => {
    let bindingCalls = 0;
    mockApi(({ method, url }) => {
      if (method === "POST" && url.endsWith("/provider-connections"))
        return json(connection(), 201);
      if (method === "POST" && url.endsWith("/probes"))
        return json(probe("passed", ["seedream-4", "seedance-2"]));
      if (method === "POST" && url.endsWith("/model-bindings")) {
        bindingCalls += 1;
        return bindingCalls === 1
          ? json({ id: "b1" }, 201)
          : json({ code: "VALIDATION", message: "合同不可用", details: {} }, 422);
      }
      return undefined;
    });
    await connectWith([MEDIA_PLUGIN]);
    const picker = await screen.findByTestId("provider-model-picker");
    for (const box of within(picker).getAllByRole("checkbox")) fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: "添加 2 个模型" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("已添加 1 个，1 个未添加");
  });

  it("lists discovered text models for a LiteLLM gateway without creating bindings", async () => {
    const calls = mockApi(({ method, url }) => {
      if (method === "POST" && url.endsWith("/provider-connections"))
        return json(
          connection({ provider_type: "litellm", protocol_profile: "openai_chat_v1" }),
          201,
        );
      if (method === "POST" && url.endsWith("/probes"))
        return json(probe("passed", ["script-quality", "fast-chat"]));
      return undefined;
    });
    wrap(<AddProviderDialog workspaceId={WS} plugins={[TEXT_PLUGIN]} onClose={() => undefined} />);
    const dialog = await screen.findByRole("dialog", { name: "添加供应商" });
    expect(within(dialog).getByLabelText("服务地址")).toHaveValue("");
    fireEvent.change(within(dialog).getByLabelText("服务地址"), {
      target: { value: "https://my-text.test/v1" },
    });
    fireEvent.change(within(dialog).getByLabelText("API Key"), { target: { value: "sk-gw" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "连接并读取模型" }));
    expect(await screen.findByText("已发现 2 个文本模型")).toBeVisible();
    expect(screen.getByText("script-quality")).toBeVisible();
    expect(calls.some((call) => call.url.endsWith("/model-bindings"))).toBe(false);
    expect(
      calls.find((call) => call.method === "POST" && call.url.endsWith("/provider-connections"))
        ?.body,
    ).toMatchObject({
      provider_type: "litellm",
      base_url: "https://my-text.test/v1",
      api_key: "sk-gw",
    });
  });
});

describe("ProviderList", () => {
  afterEach(() => vi.restoreAllMocks());

  it("offers a separate text connection and never carries Agnes edits into local deployment", async () => {
    const agnes = { ...MEDIA_PLUGIN, provider_type: "agnes", protocol_profile: "agnes_cn_v1" };
    mockApi(({ url }) => {
      if (url.endsWith("/provider-plugins")) return json([agnes, COMPAT_PLUGIN, TEXT_PLUGIN]);
      if (url.endsWith("/provider-connections"))
        return json([
          connection({
            display_name: "Agnes",
            provider_type: "agnes",
            protocol_profile: "agnes_cn_v1",
            base_url: "https://api.agnes-ai.cn",
          }),
          connection({
            id: "local",
            display_name: "本地部署",
            provider_type: "openai_compatible_media",
            protocol_profile: "openai_media_v1",
            base_url: "http://local.test:30020/v1",
          }),
        ]);
      return undefined;
    });
    wrap(<ProviderList workspaceId={WS} adding={false} onAddingChange={() => undefined} />);
    await screen.findByRole("region", { name: "配置 Agnes" });
    fireEvent.change(screen.getByLabelText("服务地址"), {
      target: { value: "https://edited.agnes.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "管理 本地部署" }));
    expect(screen.getByLabelText("服务地址")).toHaveValue("http://local.test:30020/v1");
    expect(screen.queryByText("seedream-4")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "选择 文本服务" }));
    const text = screen.getByRole("region", { name: "配置 文本服务" });
    expect(within(text).getByLabelText("API Key")).toHaveValue("");
  });

  it("keeps inline model selection through a connection refresh and creates the connection only once", async () => {
    let created = false;
    const saved = connection({ display_name: "Seedance" });
    const calls = mockApi(({ method, url }) => {
      if (url.endsWith("/provider-plugins")) return json([MEDIA_PLUGIN]);
      if (url.endsWith("/provider-connections")) {
        if (method === "POST") {
          created = true;
          return json(saved, 201);
        }
        return json(created ? [saved] : []);
      }
      if (url.endsWith("/probes") && method === "POST")
        return json(probe("passed", ["seedream-4"]));
      if (url.endsWith("/model-bindings") && method === "POST") return json({ id: "b1" }, 201);
      return undefined;
    });
    wrap(<ProviderList workspaceId={WS} adding={false} onAddingChange={() => undefined} />);
    const detail = await screen.findByRole("region", { name: "配置 Seedance" });
    fireEvent.change(within(detail).getByLabelText("API Key"), { target: { value: "mock-key" } });
    fireEvent.click(within(detail).getByRole("button", { name: "连接并读取模型" }));
    const choice = await screen.findByRole("checkbox", { name: /seedream-4/ });
    expect(screen.getByRole("region", { name: "配置 Seedance" })).toBeVisible();
    fireEvent.click(choice);
    fireEvent.click(screen.getByRole("button", { name: "添加 1 个模型" }));
    await screen.findByRole("button", { name: "管理 Seedance" });
    expect(screen.queryByRole("button", { name: "选择 Seedance" })).toBeNull();
    expect(
      calls.filter((call) => call.method === "POST" && call.url.endsWith("/provider-connections")),
    ).toHaveLength(1);
  });

  it("keeps four independent supplier entries even before official accounts are configured", async () => {
    const agnes = {
      ...MEDIA_PLUGIN,
      provider_type: "agnes",
      protocol_profile: "agnes_cn_v1",
      display_name: "Agnes",
    };
    const minimax = {
      ...MEDIA_PLUGIN,
      provider_type: "minimax",
      protocol_profile: "minimax_cn_v1",
      display_name: "MiniMax",
      default_base_url: "https://api.minimaxi.com",
    };
    const calls = mockApi(({ url }) => {
      if (url.endsWith("/provider-plugins"))
        return json([agnes, minimax, MEDIA_PLUGIN, COMPAT_PLUGIN]);
      if (url.endsWith("/provider-connections"))
        return json([
          connection({
            provider_type: "agnes",
            protocol_profile: "agnes_cn_v1",
            display_name: "Agnes",
          }),
          connection({
            id: "local",
            provider_type: "openai_compatible_media",
            protocol_profile: "openai_media_v1",
            display_name: "本地部署",
            base_url: "http://172.18.6.80:30020/v1",
          }),
          connection({
            id: "old",
            provider_type: "minimax",
            protocol_profile: "minimax_cn_v1",
            display_name: "MiniMax（旧配置）",
            enabled: false,
          }),
        ]);
      return undefined;
    });
    function Settings() {
      const [adding, setAdding] = useState(false);
      return <ProviderList workspaceId={WS} adding={adding} onAddingChange={setAdding} />;
    }
    wrap(<Settings />);
    const list = await screen.findByRole("navigation", { name: "已连接的供应商" });
    expect(within(list).getByRole("button", { name: "管理 Agnes" })).toBeVisible();
    expect(within(list).getByRole("button", { name: "管理 本地部署" })).toBeVisible();
    expect(within(list).getByRole("button", { name: "选择 Seedance" })).toBeVisible();
    expect(within(list).queryByRole("button", { name: "管理 MiniMax（旧配置）" })).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: "选择 MiniMax" }));
    expect(screen.getByRole("region", { name: "配置 MiniMax" })).toBeVisible();
    const detail = screen.getByRole("region", { name: "配置 MiniMax" });
    expect(within(detail).getByLabelText("服务地址")).toHaveValue("https://api.minimaxi.com");
    expect(within(detail).getByLabelText("API Key")).toHaveValue("");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: "选择 Seedance" }));
    const seedance = screen.getByRole("region", { name: "配置 Seedance" });
    expect(within(seedance).getByLabelText("连接名称")).toHaveValue("Seedance");
    expect(within(seedance).getByLabelText("服务地址")).toHaveValue(MEDIA_PLUGIN.default_base_url);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("shows every connection, including two of the same vendor", async () => {
    mockApi(({ url }) => {
      if (url.endsWith("/provider-plugins")) return json([MEDIA_PLUGIN]);
      if (url.endsWith("/provider-connections"))
        return json([
          connection({ verification_status: "verified" }),
          connection({
            id: "33333333-3333-4333-8333-333333333333",
            display_name: "火山 · 备用账号",
            verification_status: "failed",
          }),
        ]);
      if (url.endsWith("/model-bindings")) return json([{ id: "b1" }, { id: "b2" }]);
      return undefined;
    });
    wrap(<ProviderList workspaceId={WS} adding={false} onAddingChange={() => undefined} />);
    const list = await screen.findByRole("navigation", { name: "已连接的供应商" });
    expect(within(list).getAllByRole("button", { name: /管理/ })).toHaveLength(2);
    expect(within(list).getByText(/已连接/)).toBeVisible();
    expect(within(list).getByText(/认证失败/)).toBeVisible();
    const detail = screen.getByTestId("provider-detail");
    await waitFor(() =>
      expect(within(detail).getByRole("heading", { name: /模型.*2/ })).toBeVisible(),
    );
    fireEvent.click(within(list).getByRole("button", { name: "管理 火山 · 备用账号" }));
    expect(await screen.findByRole("region", { name: "配置 火山 · 备用账号" })).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "搜索供应商" }), {
      target: { value: "备用" },
    });
    expect(within(list).getAllByRole("button", { name: /管理/ })).toHaveLength(1);
  });
});

describe("ProviderDetails model revisions", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(["address", "key"])(
    "invalidates the old text catalog after changing the %s",
    async (field) => {
      let current = connection({
        provider_type: "litellm",
        protocol_profile: "openai_chat_v1",
        display_name: "文本服务",
        verification_status: "verified",
        verified_at: "2026-10-07T00:00:00Z",
      });
      let refreshed = false;
      mockApi(({ method, url }) => {
        if (url.endsWith("/provider-plugins")) return json([TEXT_PLUGIN]);
        if (url.endsWith("/provider-connections")) return json([current]);
        if (url.endsWith("/probes") && method === "GET") {
          // History still contains the old successful read after rotation.
          return json([probe("passed", ["old-chat"])]);
        }
        if (method !== "GET" && (url.endsWith(`/${CONN}`) || url.endsWith("/credential"))) {
          current = {
            ...current,
            base_url: "https://changed.test/v1",
            verification_status: "unverified",
            verified_at: null,
            connection_revision_id: "revision-2",
          };
          refreshed = true;
          return json(current);
        }
        return undefined;
      });
      wrap(<ProviderList workspaceId={WS} adding={false} onAddingChange={() => undefined} />);
      const panel = await screen.findByRole("region", { name: "配置 文本服务" });
      expect(await within(panel).findByText("old-chat", { exact: true })).toBeVisible();
      if (field === "address") {
        fireEvent.change(within(panel).getByLabelText("服务地址"), {
          target: { value: "https://changed.test/v1" },
        });
        fireEvent.click(within(panel).getByRole("button", { name: /^保存$/ }));
      } else {
        fireEvent.change(within(panel).getByLabelText("更换 API Key"), {
          target: { value: "new-fixture-key" },
        });
        fireEvent.click(within(panel).getByRole("button", { name: /^更换 Key$/ }));
      }
      await waitFor(() => expect(refreshed).toBe(true));
      await waitFor(() =>
        expect(within(panel).queryByText("old-chat", { exact: true })).toBeNull(),
      );
      expect(within(panel).queryByText("可用", { exact: true })).toBeNull();
      expect(within(panel).getByTestId("provider-connection-status")).toHaveTextContent("待验证");
    },
  );

  it("uses only the current revision even if an old successful read arrives last", async () => {
    mockApi(({ url }) => {
      if (url.endsWith("/probes"))
        return json([
          { ...probe("passed", ["old-chat"]), probe_id: "old" },
          {
            ...probe("passed", ["current-chat"]),
            probe_id: "current",
            connection_revision_id: "revision-2",
          },
        ]);
      return undefined;
    });
    wrap(
      <ProviderDetails
        workspaceId={WS}
        connection={connection({
          provider_type: "litellm",
          protocol_profile: "openai_chat_v1",
          display_name: "文本服务",
          verification_status: "verified",
          connection_revision_id: "revision-2",
        })}
        plugin={TEXT_PLUGIN}
      />,
    );
    expect(await screen.findByText("current-chat", { exact: true })).toBeVisible();
    expect(screen.queryByText("old-chat", { exact: true })).toBeNull();
  });

  it("allows a current contract to replace the retired binding for the same remote model", async () => {
    const oldContract = {
      ...MEDIA_PLUGIN.models[0],
      catalog_entry_id: "c-old",
      lifecycle: "retired",
    };
    const plugin = { ...MEDIA_PLUGIN, models: [oldContract, ...MEDIA_PLUGIN.models] };
    const calls = mockApi(({ method, url }) => {
      if (url.endsWith("/model-bindings") && method === "GET")
        return json([
          {
            id: "old-binding",
            model_id: "seedream-4",
            media_type: "image",
            enabled: true,
            catalog_entry_id: "c-old",
            account_verified: true,
          },
        ]);
      if (url.endsWith("/probes") && method === "POST")
        return json(probe("passed", ["seedream-4"]));
      if (url.endsWith("/model-bindings") && method === "POST")
        return json(
          {
            id: "new-binding",
            model_id: "seedream-4",
            media_type: "image",
            enabled: true,
            catalog_entry_id: "c-image",
            account_verified: true,
          },
          201,
        );
      return undefined;
    });
    wrap(
      <ProviderDetails
        workspaceId={WS}
        connection={connection({ verification_status: "verified" })}
        plugin={plugin}
      />,
    );
    expect(await screen.findByText("调用方式待更新")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "添加模型" }));
    const picker = await screen.findByTestId("provider-model-picker");
    const checkbox = within(picker).getByRole("checkbox", { name: /seedream-4/ });
    expect(checkbox).toBeEnabled();
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "添加 1 个模型" }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.method === "POST" && call.url.endsWith("/model-bindings")),
      ).toBe(true),
    );
    expect(
      calls.find((call) => call.method === "POST" && call.url.endsWith("/model-bindings"))?.body,
    ).toMatchObject({
      model_id: "seedream-4",
      capability_contract_id: "c-image",
      media_type: "image",
    });
    expect(
      calls
        .filter((call) => call.method === "POST")
        .every((call) => /\/(probes|model-bindings)$/.test(call.url)),
    ).toBe(true);
  });
});

function Activation({ role = "llm", modelId }: { role?: WorkspaceModelRole; modelId: string }) {
  const usage = useModelActivation(WS);
  const active = usage.isActive(role, modelId);
  return (
    <>
      <button
        disabled={active || !usage.canActivate(role, modelId) || usage.activate.isPending}
        onClick={() => usage.activate.mutate({ role, modelId })}
      >
        {active ? "已启用" : "启用"}
      </button>
      {usage.activate.isError && <p role="alert">{usage.activate.error.message}</p>}
    </>
  );
}
const planningSlots = ["planning.brief", "planning.script", "planning.storyboard"];
function availableModel(id: string, capability = "text.generate") {
  return { id, display_name: id, source: "workspace", available: true, capabilities: [capability] };
}

describe("saved model activation", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each([
    "video.text_to_video",
    "video.image_to_video",
    "video.last_frame_to_video",
    "video.first_last_frame",
    "video.reference_to_video",
  ])("activates an available video model supporting %s", async (capability) => {
    const profile = { id: "prof", is_default: true, version: 3, bindings: {} };
    const calls = mockApi(({ url }) => {
      if (url.endsWith("/model-profiles")) return json([profile]);
      if (url.endsWith("/model-profiles/prof") || url.endsWith("/simple-mode"))
        return json(profile);
      if (url.includes("/api/v1/models"))
        return json([availableModel("binding:video", capability)]);
      return undefined;
    });
    wrap(<Activation role="video" modelId="binding:video" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "启用" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    await waitFor(() =>
      expect(calls.find((call) => call.url.endsWith("/simple-mode"))?.body).toEqual({
        video_model_id: "binding:video",
        expected_version: 3,
      }),
    );
  });

  it("switches between saved LLM accounts with the same model name without altering credentials or media", async () => {
    const second = "33333333-3333-4333-8333-333333333333";
    const firstId = `litellm/${CONN}/chat`,
      secondId = `litellm/${second}/chat`;
    const connections = [
      connection({
        provider_type: "litellm",
        protocol_profile: "openai_chat_v1",
        display_name: "LLM A",
        base_url: "https://a.test/v1",
        verification_status: "verified",
      }),
      connection({
        id: second,
        provider_type: "litellm",
        protocol_profile: "openai_chat_v1",
        display_name: "LLM B",
        base_url: "https://b.test/v1",
        verification_status: "verified",
      }),
    ];
    let profile = {
      id: "prof",
      name: "默认",
      is_default: true,
      version: 3,
      bindings: {
        ...Object.fromEntries(
          planningSlots.map((slot) => [
            slot,
            { model_id: firstId, native_options: { temperature: 0.3 }, enabled: true },
          ]),
        ),
        "video.shot": {
          model_id: "binding:video",
          native_options: { duration: 8 },
          enabled: false,
        },
      },
    };
    const originalConnections = structuredClone(connections);
    const calls = mockApi(({ method, url, body }) => {
      if (url.endsWith("/provider-plugins")) return json([TEXT_PLUGIN]);
      if (url.endsWith("/provider-connections")) return json(connections);
      if (url.endsWith("/probes")) return json([probe("passed", ["chat"])]);
      if (url.endsWith("/model-profiles")) return json([profile]);
      if (url.endsWith("/model-profiles/prof")) return json(profile);
      if (url.includes("/api/v1/models"))
        return json([availableModel(firstId), availableModel(secondId)]);
      if (method === "POST" && url.endsWith("/simple-mode")) {
        const input = body as { llm_model_id: string; expected_version: number };
        expect(input.expected_version).toBe(profile.version);
        profile = {
          ...profile,
          version: profile.version + 1,
          bindings: {
            ...profile.bindings,
            ...Object.fromEntries(
              planningSlots.map((slot) => [
                slot,
                { model_id: input.llm_model_id, native_options: {}, enabled: true },
              ]),
            ),
          },
        };
        return json(profile);
      }
      return undefined;
    });
    wrap(<ProviderList workspaceId={WS} adding={false} onAddingChange={() => undefined} />);
    await screen.findByRole("button", { name: "已启用 chat" });
    fireEvent.click(screen.getByRole("button", { name: "管理 LLM B" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "启用 chat" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用 chat" }));
    await screen.findByRole("button", { name: "已启用 chat" });
    fireEvent.click(screen.getByRole("button", { name: "管理 LLM A" }));
    expect(screen.getByLabelText("服务地址")).toHaveValue("https://a.test/v1");
    await waitFor(() => expect(screen.getByRole("button", { name: "启用 chat" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用 chat" }));
    await screen.findByRole("button", { name: "已启用 chat" });
    expect(
      calls.filter((call) => call.method !== "GET").map((call) => [call.method, call.body]),
    ).toEqual([
      ["POST", { llm_model_id: secondId, expected_version: 3 }],
      ["POST", { llm_model_id: firstId, expected_version: 4 }],
    ]);
    expect(profile.bindings["video.shot"]).toEqual({
      model_id: "binding:video",
      native_options: { duration: 8 },
      enabled: false,
    });
    expect(connections).toEqual(originalConnections);
  });

  it("activates an image while retaining an unavailable saved text model and video settings", async () => {
    const profile = {
      id: "prof",
      is_default: true,
      version: 3,
      bindings: {
        "planning.script": { model_id: "litellm/stale/chat", native_options: { temperature: 0.3 } },
        "video.shot": {
          model_id: "binding:video",
          native_options: { duration: 8 },
          enabled: false,
        },
      },
    };
    const calls = mockApi(({ url }) => {
      if (url.endsWith("/model-profiles")) return json([profile]);
      if (url.endsWith("/model-profiles/prof") || url.endsWith("/simple-mode"))
        return json(profile);
      if (url.includes("/api/v1/models"))
        return json([availableModel("binding:image", "image.generate")]);
      return undefined;
    });
    wrap(<Activation role="image" modelId="binding:image" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "启用" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    await waitFor(() =>
      expect(calls.find((call) => call.url.endsWith("/simple-mode"))?.body).toEqual({
        image_model_id: "binding:image",
        expected_version: 3,
      }),
    );
  });

  it("explicitly re-enables the same model and preserves its parameters and other roles", async () => {
    const profile = {
      id: "prof",
      is_default: true,
      version: 3,
      bindings: {
        ...Object.fromEntries(
          planningSlots.map((slot) => [
            slot,
            { model_id: "chat", native_options: { temperature: 0.3 }, enabled: false },
          ]),
        ),
        "video.shot": {
          model_id: "binding:video",
          native_options: { duration: 8 },
          enabled: false,
        },
      },
    };
    const calls = mockApi(({ url }) => {
      if (url.endsWith("/model-profiles")) return json([profile]);
      if (url.endsWith("/model-profiles/prof")) return json(profile);
      if (url.includes("/api/v1/models")) return json([availableModel("chat")]);
      return undefined;
    });
    wrap(<Activation modelId="chat" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "启用" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    await waitFor(() =>
      expect(calls.find((call) => call.method === "PUT")?.body).toEqual({
        expected_version: 3,
        bindings: {
          ...Object.fromEntries(
            planningSlots.map((slot) => [
              slot,
              { model_id: "chat", native_options: { temperature: 0.3 }, enabled: true },
            ]),
          ),
          "video.shot": profile.bindings["video.shot"],
        },
      }),
    );
  });

  it("creates an internal default only on first activation, then applies only that role", async () => {
    const profile = { id: "prof", is_default: true, version: 1, bindings: {} };
    let created = false;
    const calls = mockApi(({ method, url }) => {
      if (url.endsWith("/model-profiles")) {
        if (method === "POST") {
          created = true;
          return json(profile, 201);
        }
        return json(created ? [profile] : []);
      }
      if (url.endsWith("/model-profiles/prof") || url.endsWith("/simple-mode"))
        return json(profile);
      if (url.includes("/api/v1/models"))
        return json([
          availableModel("chat"),
          { ...availableModel("installed"), source: "installed" },
        ]);
      return undefined;
    });
    wrap(<Activation modelId="chat" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "启用" })).toBeEnabled());
    expect(calls.every((call) => call.method === "GET")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    await waitFor(() =>
      expect(calls.find((call) => call.url.endsWith("/simple-mode"))?.body).toEqual({
        llm_model_id: "chat",
        expected_version: 1,
      }),
    );
    expect(
      calls.find((call) => call.method === "POST" && call.url.endsWith("/model-profiles"))?.body,
    ).toEqual({ name: "默认", bindings: {}, is_default: true });
  });

  it("retains a created default after activation fails instead of creating it again", async () => {
    let created = false;
    let attempts = 0;
    let profile = { id: "prof", is_default: true, version: 1, bindings: {} };
    const calls = mockApi(({ method, url }) => {
      if (url.endsWith("/model-profiles")) {
        if (method === "POST") {
          created = true;
          return json(profile, 201);
        }
        return json(created ? [profile] : []);
      }
      if (url.endsWith("/model-profiles/prof")) return json(profile);
      if (url.endsWith("/simple-mode")) {
        attempts += 1;
        if (attempts === 1) return json({ detail: "暂时无法启用" }, 503);
        profile = {
          ...profile,
          version: 2,
          bindings: Object.fromEntries(planningSlots.map((slot) => [slot, { model_id: "chat" }])),
        };
        return json(profile);
      }
      if (url.includes("/api/v1/models")) return json([availableModel("chat")]);
      return undefined;
    });
    wrap(<Activation modelId="chat" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "启用" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法启用");
    expect(attempts).toBe(1);
    await waitFor(() => expect(screen.getByRole("button", { name: "启用" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    await screen.findByRole("button", { name: "已启用" });
    expect(
      calls.filter((call) => call.method === "POST" && call.url.endsWith("/model-profiles")),
    ).toHaveLength(1);
    expect(attempts).toBe(2);
  });

  it.each(["unavailable", "installed"])("does not enable a %s model", async (reason) => {
    mockApi(({ url }) => {
      if (url.includes("/api/v1/models"))
        return json([
          {
            ...availableModel("chat"),
            ...(reason === "installed" ? { source: "installed" } : { available: false }),
          },
        ]);
      return undefined;
    });
    wrap(<Activation modelId="chat" />);
    await waitFor(() => expect(screen.getByRole("button")).toBeDisabled());
  });

  it("surfaces a version conflict without retrying or replacing another user's selection", async () => {
    let profile = { id: "prof", is_default: true, version: 3, bindings: {} };
    const calls = mockApi(({ url }) => {
      if (url.endsWith("/model-profiles")) return json([profile]);
      if (url.endsWith("/model-profiles/prof")) return json(profile);
      if (url.endsWith("/simple-mode")) {
        profile = { ...profile, version: 4 };
        return json({ code: "CONFLICT", detail: "模型配置已被修改", details: {} }, 409);
      }
      if (url.includes("/api/v1/models")) return json([availableModel("chat")]);
      return undefined;
    });
    wrap(<Activation modelId="chat" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "启用" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("模型配置已被修改");
    expect(calls.filter((call) => call.url.endsWith("/simple-mode"))).toHaveLength(1);
  });
});
