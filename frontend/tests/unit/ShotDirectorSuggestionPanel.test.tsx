import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotDirectorSuggestionPanel } from "../../src/features/director/ShotDirectorSuggestionPanel";
import type { ShotLite } from "../../src/features/shots/api";

const SHOT: ShotLite = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 5,
  director_state: { action: { description: "turns" } },
  image_prompt: "old image prompt",
  video_prompt: "old video prompt",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function suggestion(baseShotVersion = 5) {
  return {
    base_shot_version: baseShotVersion,
    suggested_image_prompt: "new image prompt",
    suggested_video_prompt: "new video prompt",
    suggested_director_state: { action: { description: "new action" } },
    change_summary: "更克制并缓慢推进",
  };
}

function renderPanel(onApplyDraft = vi.fn(), dirty = false): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ShotDirectorSuggestionPanel
        projectId="project-1"
        shot={SHOT}
        dirty={dirty}
        onApplyDraft={onApplyDraft}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ShotDirectorSuggestionPanel", () => {
  it("requests the selected shot, renders old/new diff, and applies only to draft", async () => {
    const calls: Array<{ url: string; method: string; body?: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      calls.push({ url, method, body });
      if (url.endsWith("/auth/csrf")) return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/suggestion")) return Promise.resolve(json(suggestion()));
      return Promise.resolve(json({}));
    });
    const onApplyDraft = vi.fn();
    renderPanel(onApplyDraft);

    fireEvent.change(screen.getByLabelText("导演要求"), {
      target: { value: "让情绪更克制，镜头缓慢推进" },
    });
    fireEvent.click(screen.getByTestId("request-shot-director-suggestion"));

    expect(await screen.findByTestId("shot-director-suggestion-proposal")).toBeInTheDocument();
    expect(screen.getByTestId("suggestion-old-image-prompt")).toHaveTextContent("old image prompt");
    expect(screen.getByTestId("suggestion-new-image-prompt")).toHaveTextContent("new image prompt");
    expect(screen.getByTestId("suggestion-old-video-prompt")).toHaveTextContent("old video prompt");
    expect(screen.getByTestId("suggestion-new-video-prompt")).toHaveTextContent("new video prompt");
    expect(screen.getByTestId("suggestion-change-summary")).toHaveTextContent("更克制");

    const request = calls.find((call) => call.url.endsWith("/suggestion"));
    expect(request?.method).toBe("POST");
    expect(request?.url).toBe("/api/v1/projects/project-1/director/shots/shot-1/suggestion");
    expect(request?.body).toEqual({
      scene_id: "scene-1",
      shot_id: "shot-1",
      expected_shot_version: 5,
      user_instruction: "让情绪更克制，镜头缓慢推进",
    });

    fireEvent.click(screen.getByTestId("apply-shot-director-suggestion"));
    await waitFor(() =>
      expect(onApplyDraft).toHaveBeenCalledWith({
        image_prompt: "new image prompt",
        video_prompt: "new video prompt",
        director_state: { action: { description: "new action" } },
      }),
    );
    expect(calls.some((call) => call.url.endsWith("/design"))).toBe(false);
    expect(calls.some((call) => call.url.endsWith("/execution-plan"))).toBe(false);
    expect(screen.getByTestId("apply-shot-director-suggestion")).toBeDisabled();

    fireEvent.click(screen.getByTestId("discard-shot-director-suggestion"));
    expect(screen.queryByTestId("shot-director-suggestion-proposal")).not.toBeInTheDocument();
  });

  it("blocks requests while the Shot Design draft is dirty", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    renderPanel(vi.fn(), true);
    fireEvent.change(screen.getByLabelText("导演要求"), { target: { value: "要求" } });
    expect(screen.getByTestId("request-shot-director-suggestion")).toBeDisabled();
    expect(screen.getByTestId("suggestion-dirty-guard")).toHaveTextContent("先保存或撤销");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("blocks applying a stale proposal and surfaces the backend error", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ csrf_token: "csrf" }))
      .mockResolvedValueOnce(json(suggestion(4)));
    renderPanel();
    fireEvent.change(screen.getByLabelText("导演要求"), { target: { value: "要求" } });
    fireEvent.click(screen.getByTestId("request-shot-director-suggestion"));
    await screen.findByTestId("suggestion-stale-guard");
    expect(screen.getByTestId("apply-shot-director-suggestion")).toBeDisabled();

    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ csrf_token: "csrf" }))
      .mockResolvedValueOnce(
        json({ detail: "导演服务暂不可用", code: "DIRECTOR_SUGGESTION_FAILED" }, 422),
      );
    // A new render keeps the test focused on the user-visible server message.
    renderPanel();
    fireEvent.change(screen.getAllByLabelText("导演要求").at(-1)!, { target: { value: "要求" } });
    fireEvent.click(screen.getAllByTestId("request-shot-director-suggestion").at(-1)!);
    expect(await screen.findByText(/导演服务暂不可用/)).toBeInTheDocument();
  });
});
