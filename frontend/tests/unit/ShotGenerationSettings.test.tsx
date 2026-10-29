import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotGenerationSettings } from "../../src/features/shots/ShotGenerationSettings";
import { queryKeys } from "../../src/lib/queryKeys";
import { expectSelectValue, selectValue } from "./selectValue";

const parameter = (type: string, extra: Record<string, unknown> = {}) => ({
  type,
  required: false,
  sensitive: false,
  deprecated: false,
  ...extra,
});
function capabilities(fixed = false) {
  return {
    report: { model_id: "test/image", model_revision: "r1", manifest_hash: "a".repeat(64) },
    resolution: { invoke_model_value: "remote-image", source: "project_profile" },
    connection_label: "我的模型连接",
    generation_options: {
      aspect_ratio: {
        parameter: parameter("string", { enum: fixed ? ["1:1"] : ["16:9", "9:16"] }),
        editable: !fixed,
        reason: fixed ? "fixed_value" : null,
        inherited_value: "16:9",
        inherited_source: "project",
      },
      duration_seconds: {
        parameter: parameter("integer", { enum: [5, 8] }),
        editable: true,
        inherited_value: 8,
        inherited_source: "project_profile",
      },
      seed: {
        parameter: parameter("integer", { minimum: 0 }),
        editable: true,
        inherited_value: 7,
        inherited_source: "project_profile",
      },
      generate_audio: {
        parameter: parameter("boolean"),
        editable: true,
        inherited_value: true,
        inherited_source: "contract_default",
      },
      fps: { parameter: parameter("integer"), editable: false, reason: "compiler_unavailable" },
    },
  };
}
function json(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }),
  );
}
function Editor({ initial = {} }: { initial?: Record<string, unknown> }) {
  const [settings, setSettings] = useState(initial);
  return (
    <>
      <ShotGenerationSettings
        projectId="p1"
        stage="video"
        mode="text_to_video"
        settings={settings}
        onChange={setSettings}
      />
      <output data-testid="settings">{JSON.stringify(settings)}</output>
    </>
  );
}
function setup(initial?: Record<string, unknown>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Editor initial={initial} />
    </QueryClientProvider>,
  );
  return client;
}
function open() {
  fireEvent.click(screen.getByText("视频生成参数"));
}

describe("Shot generation settings", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads only expanded capabilities and displays model, connection, revision and inherited values", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(capabilities()));
    setup();
    expect(fetch).not.toHaveBeenCalled();
    open();
    expect(await screen.findByText(/remote-image/)).toHaveTextContent("我的模型连接");
    expect(screen.getByText(/合同：r1/)).toBeInTheDocument();
    expectSelectValue(screen.getByLabelText("视频生成时长（秒）"), "8");
    await selectValue(screen.getByLabelText("视频生成时长（秒）"), "5");
    expect(JSON.parse(screen.getByTestId("settings").textContent!)).toMatchObject({
      common_options: { duration_seconds: 5 },
    });
    fireEvent.click(
      within(screen.getByTestId("shot-generation-options-video")).getByText("恢复继承"),
    );
    expect(
      JSON.parse(screen.getByTestId("settings").textContent!).common_options,
    ).not.toHaveProperty("duration_seconds");
  });

  it("preserves numeric zero and boolean false, and migrates the legacy duration only on explicit edit", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json(capabilities()));
    setup({ request_duration_seconds: 5, native_options: { seed: 9 } });
    open();
    await screen.findByText(/remote-image/);
    fireEvent.click(screen.getByText("高级参数"));
    fireEvent.change(screen.getByLabelText("随机种子"), { target: { value: "0" } });
    fireEvent.click(screen.getByLabelText("生成原生声音"));
    await selectValue(screen.getByLabelText("视频生成时长（秒）"), "8");
    const settings = JSON.parse(screen.getByTestId("settings").textContent!);
    expect(settings.common_options).toEqual({
      seed: 0,
      generate_audio: false,
      duration_seconds: 8,
    });
    expect(settings.native_options).toEqual({});
    expect(settings).not.toHaveProperty("request_duration_seconds");
  });

  it("requires explicit adoption of a fixed 1:1 ratio and retains incompatible values until removed", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json(capabilities(true)));
    setup({ common_options: { fps: 24, duration_seconds: 10 } });
    open();
    expect(await screen.findByText(/当前参数不符合模型固定输出/)).toBeInTheDocument();
    expect(screen.queryByLabelText("输出比例")).not.toBeInTheDocument();
    expect(
      JSON.parse(screen.getByTestId("settings").textContent!).common_options,
    ).not.toHaveProperty("aspect_ratio");
    fireEvent.click(screen.getByText("采用模型固定值"));
    expect(
      JSON.parse(screen.getByTestId("settings").textContent!).common_options.aspect_ratio,
    ).toBe("1:1");
    fireEvent.click(screen.getByText("移除不兼容参数"));
    expect(JSON.parse(screen.getByTestId("settings").textContent!).common_options).toEqual({
      aspect_ratio: "1:1",
    });
  });

  it.each([
    { request_duration_seconds: 10 },
    { common_options: { duration: 10 } },
    { native_options: { duration: 10 } },
    { request_duration_seconds: 5, common_options: { duration_seconds: 8 } },
  ])(
    "removes every saved duration form after explicit incompatible cleanup: %j",
    async (initial) => {
      vi.spyOn(globalThis, "fetch").mockImplementation(() => json(capabilities()));
      setup({ ...initial, unrelated_draft: "keep" });
      open();
      await screen.findByText(/remote-image/);
      fireEvent.click(screen.getByText("移除不兼容参数"));
      expect(JSON.parse(screen.getByTestId("settings").textContent!)).toEqual({
        common_options: {},
        native_options: {},
        unrelated_draft: "keep",
      });
      expect(screen.queryByText("移除不兼容参数")).not.toBeInTheDocument();
      expectSelectValue(screen.getByLabelText("视频生成时长（秒）"), "8");
    },
  );

  it("rechecks changed model contracts without silently migrating a Shot override", async () => {
    let response = capabilities();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json(response));
    const client = setup({ common_options: { aspect_ratio: "9:16" } });
    open();
    await screen.findByText(/remote-image/);
    response = capabilities(true);
    await client.invalidateQueries({ queryKey: queryKeys.model.generationOptionsRoot("p1") });
    await waitFor(() => expect(screen.getByText(/当前参数不符合模型固定输出/)).toBeInTheDocument());
    expect(
      JSON.parse(screen.getByTestId("settings").textContent!).common_options.aspect_ratio,
    ).toBe("9:16");
  });

  it("uses distinct capability cache entries for workspaces and projects", () => {
    const key = queryKeys.model.generationOptions;
    expect(key("p1", "w1", "video", "text_to_video")).not.toEqual(
      key("p1", "w2", "video", "text_to_video"),
    );
    expect(key("p1", "w1", "video", "text_to_video")).not.toEqual(
      key("p2", "w1", "video", "text_to_video"),
    );
  });

  it("does not silently rebind saved options when the model contract changes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json(capabilities()));
    setup({ source_contract_hash: "old-contract", common_options: { duration_seconds: 5 } });
    open();
    await screen.findByText(/模型合同已变化/);
    await selectValue(screen.getByLabelText("视频生成时长（秒）"), "8");
    expect(JSON.parse(screen.getByTestId("settings").textContent!).source_contract_hash).toBe(
      "old-contract",
    );
    fireEvent.click(screen.getByText("已核对，采用当前合同"));
    expect(JSON.parse(screen.getByTestId("settings").textContent!).source_contract_hash).toBe(
      "a".repeat(64),
    );
  });
});
