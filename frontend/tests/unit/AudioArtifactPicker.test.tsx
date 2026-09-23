import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AudioArtifactPicker } from "../../src/features/editing/AudioArtifactPicker";
import { fetchEditingAudioArtifacts } from "../../src/features/editing/api";

function audio(id: string) {
  return {
    id,
    object_key: `media/${id}.wav`,
    content_hash: "hash",
    byte_size: 16000,
    mime_type: "audio/wav",
    storage_state: "available",
    produced_by_run_id: null,
    width: null,
    height: null,
    duration_seconds: "2.5",
  };
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function mount(initial = "", onChange = vi.fn(), allowMute = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Harness() {
    const [value, setValue] = useState(initial);
    const [muted, setMuted] = useState(false);
    return (
      <QueryClientProvider client={client}>
        <AudioArtifactPicker
          projectId="project-1"
          label="背景音乐"
          defaultLabel="不使用背景音乐"
          testId="audio-choice"
          value={value}
          muted={muted}
          allowMute={allowMute}
          onChange={(id, mute) => {
            setValue(id);
            setMuted(mute);
            onChange(id, mute);
          }}
        />
      </QueryClientProvider>
    );
  }
  render(<Harness />);
  return onChange;
}
afterEach(() => vi.restoreAllMocks());

describe("AudioArtifactPicker", () => {
  it("loads bounded audio pages on demand and selects actual Artifact identities without writes", async () => {
    const calls: URL[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      expect(init?.method ?? "GET").toBe("GET");
      const url = new URL(String(input), "http://test");
      calls.push(url);
      return json(
        url.searchParams.has("cursor")
          ? { items: [audio("artifact-audio-2")], next_cursor: null }
          : { items: [audio("artifact-audio-1")], next_cursor: "cursor+one=" },
      );
    });
    const changed = mount();
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "选择背景音乐" }));
    await screen.findByRole("button", { name: "使用音频 1" });
    expect(calls).toHaveLength(1);
    expect(calls[0].searchParams.get("usable_audio")).toBe("true");
    expect(calls[0].searchParams.get("limit")).toBe("25");
    expect(screen.getByLabelText("试听音频 1")).toHaveAttribute(
      "src",
      expect.stringContaining("/artifacts/artifact-audio-1/content"),
    );
    fireEvent.click(screen.getByRole("button", { name: "下一页音频" }));
    await screen.findByRole("button", { name: "使用音频 26" });
    expect(calls[1].searchParams.get("cursor")).toBe("cursor+one=");
    expect(screen.getByRole("button", { name: "下一页音频" })).toBeDisabled();
    expect(changed).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "使用音频 26" }));
    expect(changed).toHaveBeenCalledWith("artifact-audio-2", false);
    expect(screen.getByTestId("audio-choice")).toHaveValue("artifact-audio-2");
    expect(screen.getByLabelText("背景音乐试听")).toHaveAttribute(
      "src",
      expect.stringContaining("artifact-audio-2/content"),
    );
    expect(calls).toHaveLength(2);
  });

  it("keeps a saved reference through missing pages, load errors and failed playback", async () => {
    let fail = true;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      fail
        ? json({ detail: "temporarily unavailable" }, 503)
        : json({ items: [], next_cursor: null }),
    );
    const changed = mount("saved-audio");
    fireEvent.click(screen.getByRole("button", { name: "选择背景音乐" }));
    await screen.findByText(/音频读取失败/);
    expect(screen.getByTestId("audio-choice")).toHaveValue("saved-audio");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "刷新音频" }));
    await screen.findByText(/当前没有可用音频结果/);
    fireEvent.error(screen.getByLabelText("背景音乐试听"));
    expect(screen.getByText(/已保留原选择/)).toBeInTheDocument();
    expect(screen.getByTestId("audio-choice")).toHaveValue("saved-audio");
    expect(changed).not.toHaveBeenCalled();
  });

  it("distinguishes muting from inheriting a shot's default dialogue", () => {
    const changed = mount("", undefined, true);
    fireEvent.change(screen.getByTestId("audio-choice"), { target: { value: "__muted__" } });
    expect(changed).toHaveBeenLastCalledWith("", true);
    fireEvent.change(screen.getByTestId("audio-choice"), { target: { value: "" } });
    expect(changed).toHaveBeenLastCalledWith("", false);
  });

  it("never substitutes an Asset or non-audio response from an outdated server", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ items: [{ ...audio("image"), mime_type: "image/png" }], next_cursor: null }),
    );
    const changed = mount();
    fireEvent.click(screen.getByRole("button", { name: "选择背景音乐" }));
    await screen.findByText(/音频列表回执不完整/);
    expect(screen.queryByRole("button", { name: /使用音频/ })).not.toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });

  it("rejects repeated cursors instead of looping through a corrupt page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ items: [], next_cursor: "same" }));
    await expect(fetchEditingAudioArtifacts("project-1", "same")).rejects.toThrow(
      "音频列表回执不完整",
    );
  });
});
