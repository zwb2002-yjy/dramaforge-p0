import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddProviderDialog } from "../../src/components/provider/AddProviderDialog";
import { DefaultModelSettings } from "../../src/components/provider/DefaultModelSettings";
import { ProviderList } from "../../src/components/provider/ProviderList";
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
    expect(within(picker).getByText("Seedream 4")).toBeVisible();
    expect(within(picker).getByText("Seedance 2")).toBeVisible();
    // Unknown ids are listed but never bound by name guessing.
    expect(within(picker).getByText("已发现 · 暂未支持执行 1")).toBeInTheDocument();
    fireEvent.click(within(picker).getByRole("checkbox", { name: /Seedream 4/ }));
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
      display_name: "火山方舟",
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
    wrap(
      <AddProviderDialog
        workspaceId={WS}
        plugins={[MEDIA_PLUGIN, TEXT_PLUGIN]}
        onClose={() => undefined}
      />,
    );
    const dialog = await screen.findByRole("dialog", { name: "添加供应商" });
    fireEvent.click(within(dialog).getByRole("button", { name: /LiteLLM/ }));
    expect(within(dialog).getByLabelText("服务地址")).toHaveValue("http://litellm:4000");
    fireEvent.change(within(dialog).getByLabelText("API Key"), { target: { value: "sk-gw" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "连接并读取模型" }));
    expect(await screen.findByText("已发现 2 个文本模型")).toBeVisible();
    expect(screen.getByText("script-quality")).toBeVisible();
    expect(calls.some((call) => call.url.endsWith("/model-bindings"))).toBe(false);
  });
});

describe("ProviderList", () => {
  afterEach(() => vi.restoreAllMocks());

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

describe("DefaultModelSettings", () => {
  afterEach(() => vi.restoreAllMocks());

  it("offers only workspace models and creates the default profile on first save", async () => {
    const calls = mockApi(({ method, url }) => {
      if (url.endsWith("/model-profiles") && method === "GET") return json([]);
      if (url.endsWith("/model-profiles") && method === "POST")
        return json(
          { id: "prof-1", name: "默认", is_default: true, version: 1, bindings: {} },
          201,
        );
      if (url.endsWith("/simple-mode"))
        return json({ id: "prof-1", name: "默认", is_default: true, version: 2, bindings: {} });
      if (url.includes("/api/v1/models"))
        return json([
          {
            id: "litellm/script-quality",
            provider_id: "litellm",
            display_name: "实例网关",
            enabled: true,
            configured: true,
            available: true,
            capabilities: ["text.generate"],
            source: "installed",
          },
          {
            id: `litellm/${CONN}/script-quality`,
            provider_id: "litellm",
            display_name: "script-quality · 我的网关",
            enabled: true,
            configured: true,
            available: true,
            capabilities: ["text.generate"],
            source: "workspace",
          },
          {
            id: "binding:b1",
            provider_id: "volcengine",
            display_name: "Seedream 4 · 火山方舟",
            enabled: true,
            configured: true,
            available: true,
            capabilities: ["image.generate"],
            source: "workspace",
          },
        ]);
      return undefined;
    });
    wrap(<DefaultModelSettings workspaceId={WS} onAddProvider={() => undefined} />);
    const text = await screen.findByLabelText("文本模型");
    await waitFor(() => expect(text).toBeEnabled());
    expect(within(text).queryByText("实例网关")).toBeNull();
    expect(screen.getByText("还没有可用的视频模型")).toBeVisible();
    fireEvent.change(text, { target: { value: `litellm/${CONN}/script-quality` } });
    fireEvent.change(screen.getByLabelText("图片模型"), { target: { value: "binding:b1" } });
    fireEvent.click(screen.getByTestId("save-default-models"));
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/simple-mode"))).toBe(true));
    expect(
      calls.find((call) => call.method === "POST" && call.url.endsWith("/model-profiles"))?.body,
    ).toEqual({ name: "默认", bindings: {}, is_default: true });
    expect(calls.find((call) => call.url.endsWith("/simple-mode"))?.body).toEqual({
      llm_model_id: `litellm/${CONN}/script-quality`,
      image_model_id: "binding:b1",
      expected_version: 1,
    });
  });
});
