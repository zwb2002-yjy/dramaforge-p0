import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotVoiceSettings } from "../../src/features/shots/ShotVoiceSettings";
import { queryKeys } from "../../src/lib/queryKeys";
import {
  fetchVoiceOptions,
  type ShotVoiceSettings as VoiceSettings,
  type VoiceOptionsRead,
} from "../../src/features/shots/api";

const OPTIONS: VoiceOptionsRead = {
  engine: "edge-tts",
  enabled: true,
  status: "configured",
  default_voice: "catalog-woman",
  network: true,
  service_notice: "联网神经配音·Edge（非官方服务，无SLA）；仅读取配置，尚未验证服务可用性。",
  voices: [
    { id: "catalog-woman", label: "目录女声", locale: "zh-CN" },
    { id: "catalog-man", label: "目录男声", locale: "zh-CN" },
  ],
};

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderSettings(initial: VoiceSettings = { voice_id: null, rate_percent: 0 }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const changed = vi.fn();
  function Harness() {
    const [value, setValue] = useState(initial);
    return (
      <ShotVoiceSettings
        projectId="project-1"
        value={value}
        onChange={(next) => {
          changed(next);
          setValue(next);
        }}
      />
    );
  }
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  return { changed, client };
}

afterEach(() => vi.restoreAllMocks());

describe("ShotVoiceSettings", () => {
  it("reads the server catalog without probing and only changes the local draft", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(OPTIONS));
    const { changed } = renderSettings();
    expect(screen.getByRole("status")).toHaveTextContent("正在读取音色配置");
    expect(await screen.findByRole("option", { name: "目录男声 · zh-CN" })).toBeInTheDocument();
    expect(screen.getByText(OPTIONS.service_notice)).toBeInTheDocument();
    expect(screen.getByText(/对白文本将发送至微软/)).toHaveTextContent("失败不会回退为旧机械音");
    expect(screen.getByLabelText("配音音色")).toHaveValue("");
    expect(screen.getByRole("option", { name: "沿用实例默认（目录女声）" })).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("配音音色"), { target: { value: "voice:catalog-man" } });
    expect(changed).toHaveBeenLastCalledWith({ voice_id: "catalog-man", rate_percent: 0 });
    for (const rate of [-30, 0, 30]) {
      fireEvent.change(screen.getByLabelText("配音语速"), { target: { value: String(rate) } });
      expect(changed).toHaveBeenLastCalledWith({ voice_id: "catalog-man", rate_percent: rate });
    }
    expect(screen.getByLabelText("配音语速")).toHaveAttribute("min", "-30");
    expect(screen.getByLabelText("配音语速")).toHaveAttribute("max", "30");
    expect(screen.getByLabelText("配音语速")).toHaveAttribute("step", "1");
    fireEvent.change(screen.getByLabelText("配音音色"), { target: { value: "" } });
    expect(changed).toHaveBeenLastCalledWith({ voice_id: null, rate_percent: 30 });
    expect(screen.queryByRole("button", { name: /生成|试听/ })).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/projects/project-1/voice-options");
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    expect(fetch.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("keeps an unknown saved voice through catalog load and speed changes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json(OPTIONS));
    const { changed } = renderSettings({ voice_id: "retired-voice", rate_percent: -10 });
    expect(screen.getByLabelText("配音音色")).toHaveValue("voice:retired-voice");
    expect(await screen.findByRole("alert")).toHaveTextContent("不会静默切换到默认音色");
    expect(
      screen.getByRole("option", { name: /未在当前目录中的音色.*retired-voice/ }),
    ).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("配音语速"), { target: { value: "12" } });
    expect(changed).toHaveBeenLastCalledWith({ voice_id: "retired-voice", rate_percent: 12 });
  });

  it("does not replace a saved selection on a read failure and retries only the GET", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    const { changed } = renderSettings({ voice_id: "saved-voice", rate_percent: 8 });
    expect(await screen.findByRole("alert")).toHaveTextContent("当前音色和语速已保留");
    expect(screen.getByLabelText("配音音色")).toHaveValue("voice:saved-voice");
    expect(screen.getByLabelText("配音音色")).toBeDisabled();
    expect(screen.getByLabelText("配音语速")).toHaveValue("8");
    expect(changed).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockImplementation(() => json(OPTIONS));
    fireEvent.click(screen.getByRole("button", { name: "重新读取音色" }));
    await screen.findByRole("option", { name: "目录男声 · zh-CN" });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("配音音色")).toHaveValue("voice:saved-voice");
    expect(changed).not.toHaveBeenCalled();
    expect(
      fetch.mock.calls.every(
        ([url, init]) => String(url).endsWith("/voice-options") && !init?.method,
      ),
    ).toBe(true);
  });

  it("does not present stale configuration as current after a failed refresh", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(OPTIONS));
    const { client, changed } = renderSettings({ voice_id: "catalog-man", rate_percent: 0 });
    await screen.findByRole("option", { name: "目录男声 · zh-CN" });
    fetch.mockRejectedValue(new Error("offline"));
    await act(async () => {
      await client.invalidateQueries({ queryKey: queryKeys.shot.voiceOptions("project-1") });
    });
    await waitFor(() => expect(screen.getByLabelText("配音音色")).toBeDisabled());
    expect(screen.queryByText(OPTIONS.service_notice)).not.toBeInTheDocument();
    expect(screen.getByLabelText("配音音色")).toHaveValue("voice:catalog-man");
    expect(changed).not.toHaveBeenCalled();
  });

  it.each(["disabled", "invalid"] as const)(
    "shows %s configuration without changing saved settings",
    async (status) => {
      const notice = "本地配置说明：尚未连接或验证服务。";
      vi.spyOn(globalThis, "fetch").mockImplementation(() =>
        json({
          ...OPTIONS,
          status,
          enabled: status !== "disabled",
          network: false,
          service_notice: notice,
        }),
      );
      const { changed } = renderSettings({ voice_id: "catalog-man", rate_percent: 5 });
      expect(await screen.findByText(notice)).toBeInTheDocument();
      expect(
        screen.getByText(status === "disabled" ? /配音服务未启用/ : /配音配置无效/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/对白文本将发送至微软/)).not.toBeInTheDocument();
      expect(changed).not.toHaveBeenCalled();
    },
  );

  it("rejects a malformed catalog instead of claiming the voice list is empty", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({}));
    renderSettings();
    expect(await screen.findByRole("alert")).toHaveTextContent("音色目录读取失败");
    expect(screen.queryByText(/当前配置未提供可选音色/)).not.toBeInTheDocument();
  });

  it("URL-encodes the project and passes cancellation to the shared GET client", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(OPTIONS));
    const signal = new AbortController().signal;
    await expect(fetchVoiceOptions("project/one", signal)).resolves.toEqual(OPTIONS);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/projects/project%2Fone/voice-options");
    expect(fetch.mock.calls[0][1]?.signal).toBe(signal);
  });
});
