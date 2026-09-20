import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotDesignPanel, type ShotDesignDraft } from "../../src/features/shots/ShotDesignPanel";
import type { ShotLite, VoiceOptionsRead } from "../../src/features/shots/api";

const SHOT: ShotLite = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A waits",
  dialogue: "原始对白",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 4,
  director_state: { expression: { mood: "calm" } },
  image_prompt: "image",
  video_prompt: "video",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};
const OPTIONS: VoiceOptionsRead = {
  engine: "edge-tts",
  enabled: true,
  status: "configured",
  default_voice: "voice-a",
  network: true,
  service_notice: "联网神经配音·Edge（非官方服务，无SLA）；配置未验证。",
  voices: [
    { id: "voice-a", label: "目录声音甲", locale: "zh-CN" },
    { id: "voice-b", label: "目录声音乙", locale: "zh-CN" },
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
function backend({
  fail,
  freshShot = SHOT,
}: { fail?: "canvas" | "design"; freshShot?: ShotLite } = {}) {
  const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    calls.push({ url, method, body });
    if (url.endsWith("/voice-options")) return json(OPTIONS);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "test-csrf" });
    if (url.endsWith("/workbench")) return json({ shot: freshShot });
    if (method === "PATCH" && fail && url.endsWith("/" + fail)) {
      return json(
        {
          code: "CONFLICT",
          detail: "版本冲突",
          details: { expected_version: 4, actual_version: 9 },
        },
        409,
      );
    }
    if (url.endsWith("/canvas"))
      return json({
        shot: { ...SHOT, ...body, version: 7 },
        revision_id: "revision-1",
        revision_number: 1,
      });
    if (url.endsWith("/design")) return json({ ...SHOT, ...body, version: 8 });
    return json({});
  });
  return { calls, writes: () => calls.filter((call) => call.method !== "GET") };
}
function renderPanel(shot: ShotLite = SHOT) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onSaved = vi.fn();
  function panel(applyDraft?: ShotDesignDraft) {
    return (
      <QueryClientProvider client={client}>
        <ShotDesignPanel
          projectId="project-1"
          shot={shot}
          onSaved={onSaved}
          applyDraft={applyDraft}
        />
      </QueryClientProvider>
    );
  }
  const view = render(panel());
  return { onSaved, applySuggestion: (draft: ShotDesignDraft) => view.rerender(panel(draft)) };
}
async function selectVoice() {
  await screen.findByRole("option", { name: "目录声音乙 · zh-CN" });
  fireEvent.change(screen.getByLabelText("配音音色"), { target: { value: "voice:voice-b" } });
}
function editDialogue(text = "新的镜头旁白") {
  fireEvent.change(screen.getByLabelText("对白／旁白文本"), { target: { value: text } });
}
function save() {
  fireEvent.click(screen.getByRole("button", { name: "保存设计" }));
}

afterEach(() => vi.restoreAllMocks());

describe("ShotDesignPanel dialogue and voice gates", () => {
  it("does not materialize defaults or write anything merely by opening the panel", async () => {
    const { writes } = backend();
    renderPanel();
    await screen.findByRole("option", { name: "目录声音甲 · zh-CN" });
    expect(screen.getByLabelText("对白／旁白文本")).toHaveValue("原始对白");
    expect(screen.getByLabelText("配音音色")).toHaveValue("");
    expect(screen.getByLabelText("配音语速")).toHaveValue("0");
    expect(screen.getByRole("button", { name: "保存设计" })).toBeDisabled();
    expect(screen.getByText(/保存只更新本镜头设置/)).toHaveTextContent("导出成片 MP4");
    expect(writes()).toEqual([]);
  });

  it("saves dialogue through canvas only, without a voice or production mutation", async () => {
    const { writes } = backend();
    const { onSaved } = renderPanel();
    editDialogue();
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({
      url: "/api/v1/projects/project-1/shots/shot-1/canvas",
      method: "PATCH",
      body: {
        expected_version: 4,
        dialogue: "新的镜头旁白",
        visual_description: "A waits",
        source: "user",
      },
    });
    expect(writes()[0].body).not.toHaveProperty("director_state");
  });

  it("saves voice and integer rate through design only and preserves other director fields", async () => {
    const { writes } = backend();
    const { onSaved } = renderPanel();
    await selectVoice();
    fireEvent.change(screen.getByLabelText("配音语速"), { target: { value: "-15" } });
    expect(writes()).toEqual([]);
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({
      url: "/api/v1/projects/project-1/shots/shot-1/design",
      method: "PATCH",
      body: {
        expected_version: 4,
        director_state: {
          expression: { mood: "calm" },
          voice: { voice_id: "voice-b", rate_percent: -15 },
        },
      },
    });
    expect(writes()[0].body).not.toHaveProperty("dialogue");
    // A mutation response does not pretend to be a fresh server snapshot.
    expect(screen.getByTestId("shot-design-dirty")).toBeInTheDocument();
  });

  it("chains the canvas receipt version into design when dialogue and voice both change", async () => {
    const { writes } = backend();
    const { onSaved } = renderPanel();
    editDialogue();
    await selectVoice();
    fireEvent.change(screen.getByLabelText("配音语速"), { target: { value: "30" } });
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(writes().map((call) => [call.method, call.url.split("/").at(-1)])).toEqual([
      ["PATCH", "canvas"],
      ["PATCH", "design"],
    ]);
    expect(writes()[0].body).toMatchObject({ expected_version: 4, dialogue: "新的镜头旁白" });
    expect(writes()[1].body).toMatchObject({
      expected_version: 7,
      director_state: { voice: { voice_id: "voice-b", rate_percent: 30 } },
    });
  });

  it("keeps unknown voice identities in saves until the user explicitly changes them", async () => {
    const { writes } = backend();
    const { onSaved } = renderPanel({
      ...SHOT,
      director_state: { voice: { voice_id: "legacy-voice", rate_percent: 0 } },
    });
    await screen.findByText(/当前音色不在此引擎的目录中/);
    fireEvent.change(screen.getByLabelText("配音语速"), { target: { value: "-30" } });
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(writes()[0].body).toMatchObject({
      director_state: { voice: { voice_id: "legacy-voice", rate_percent: -30 } },
    });
  });

  it("persists an explicit return to the instance default as null, not the current default ID", async () => {
    const { writes } = backend();
    const { onSaved } = renderPanel({
      ...SHOT,
      director_state: { voice: { voice_id: "voice-b", rate_percent: 10 } },
    });
    await screen.findByRole("option", { name: "沿用实例默认（目录声音甲）" });
    fireEvent.change(screen.getByLabelText("配音音色"), { target: { value: "" } });
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(writes()[0].body).toMatchObject({
      director_state: { voice: { voice_id: null, rate_percent: 10 } },
    });
  });

  it.each(["canvas", "design"] as const)(
    "retains dialogue and voice after a %s conflict without automatic retries",
    async (fail) => {
      const { writes } = backend({ fail });
      const { onSaved } = renderPanel();
      if (fail === "canvas") editDialogue();
      await selectVoice();
      save();
      expect(await screen.findByTestId("shot-design-conflict")).toHaveTextContent("草稿已保留");
      expect(screen.getByLabelText("对白／旁白文本")).toHaveValue(
        fail === "canvas" ? "新的镜头旁白" : "原始对白",
      );
      expect(screen.getByLabelText("配音音色")).toHaveValue("voice:voice-b");
      expect(writes()).toHaveLength(1);
      expect(onSaved).not.toHaveBeenCalled();
      expect(screen.getByTestId("shot-design-dirty")).toBeInTheDocument();
    },
  );

  it("keeps dialogue and voice while applying a visual-only Director suggestion", async () => {
    const { writes } = backend();
    const { applySuggestion } = renderPanel();
    editDialogue();
    await selectVoice();
    fireEvent.change(screen.getByLabelText("配音语速"), { target: { value: "6" } });
    applySuggestion({
      image_prompt: "suggested image",
      video_prompt: "suggested video",
      director_state: { expression: { mood: "happy" } },
    });
    expect(screen.getByLabelText("对白／旁白文本")).toHaveValue("新的镜头旁白");
    expect(screen.getByLabelText("配音音色")).toHaveValue("voice:voice-b");
    expect(screen.getByLabelText("配音语速")).toHaveValue("6");
    expect(screen.getByLabelText("图片提示词")).toHaveValue("suggested image");
    expect(writes()).toEqual([]);
  });

  it.each([-31, 31, 0.5, null, "fast"])(
    "rejects invalid advanced rate %s before either save gate",
    async (rate) => {
      const { writes } = backend();
      renderPanel();
      editDialogue();
      const text = JSON.stringify({ voice: { voice_id: null, rate_percent: rate } });
      fireEvent.change(screen.getByLabelText("导演状态"), { target: { value: text } });
      save();
      await waitFor(() =>
        expect(screen.getByTestId("shot-design-message")).toHaveTextContent(
          "配音语速必须是 -30 到 30 之间的整数",
        ),
      );
      expect(screen.getByLabelText("导演状态")).toHaveValue(text);
      expect(screen.getByLabelText("对白／旁白文本")).toHaveValue("新的镜头旁白");
      expect(writes()).toEqual([]);
    },
  );

  it("does not erase malformed JSON when the structured voice controls cannot read it", async () => {
    const { writes } = backend();
    renderPanel();
    fireEvent.change(screen.getByLabelText("导演状态"), { target: { value: '{"voice":' } });
    expect(screen.getByText(/高级导演参数中的配音设置暂时无效/)).toBeInTheDocument();
    expect(screen.queryByLabelText("配音音色")).not.toBeInTheDocument();
    editDialogue();
    save();
    await waitFor(() =>
      expect(screen.getByTestId("shot-design-message")).toHaveTextContent("保存失败"),
    );
    expect(screen.getByLabelText("导演状态")).toHaveValue('{"voice":');
    expect(writes()).toEqual([]);
  });

  it("adopts the explicitly reloaded dialogue and voice without reseeding stale props", async () => {
    const freshShot = {
      ...SHOT,
      version: 9,
      dialogue: "服务器新对白",
      director_state: { voice: { voice_id: "voice-a", rate_percent: -7 } },
    };
    const { writes } = backend({ fail: "design", freshShot });
    const { onSaved } = renderPanel();
    await selectVoice();
    save();
    await screen.findByTestId("shot-design-conflict");
    fireEvent.click(screen.getByRole("button", { name: "载入服务器最新设计并重新检查" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("对白／旁白文本")).toHaveValue("服务器新对白");
    expect(screen.getByLabelText("配音音色")).toHaveValue("voice:voice-a");
    expect(screen.getByLabelText("配音语速")).toHaveValue("-7");
    expect(writes()).toHaveLength(1);
  });
});
