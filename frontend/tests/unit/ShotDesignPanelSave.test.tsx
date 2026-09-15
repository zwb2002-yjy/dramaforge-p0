import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotDesignPanel } from "../../src/features/shots/ShotDesignPanel";
import type { ShotLite } from "../../src/features/shots/api";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

const SHOT = {
  id: "11111111-1111-4111-8111-111111111111",
  project_id: PROJECT_ID,
  scene_id: "22222222-2222-4222-8222-222222222222",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A waits",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 4,
  director_state: { framing: "medium" },
  image_prompt: "server image prompt",
  video_prompt: "server video prompt",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
} as unknown as ShotLite;

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <ShotDesignPanel projectId={PROJECT_ID} shot={SHOT} onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return { onSaved };
}

function editImagePrompt(value: string) {
  fireEvent.change(screen.getByLabelText("图片提示词"), { target: { value } });
}

describe("ShotDesignPanel save feedback", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the saved version when the draft matches the server value", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({}));
    renderPanel();

    expect(screen.getByTestId("shot-design-saved-state")).toHaveTextContent("已保存设计 v4");
    expect(screen.queryByTestId("shot-design-dirty")).not.toBeInTheDocument();
  });

  it("distinguishes an unsaved draft from the saved server version", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({}));
    renderPanel();

    editImagePrompt("local draft prompt");

    expect(screen.getByTestId("shot-design-dirty")).toBeInTheDocument();
    expect(screen.queryByTestId("shot-design-saved-state")).not.toBeInTheDocument();
  });

  it("keeps the local draft and offers an explicit reload on a version conflict", async () => {
    const reads: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (init?.method === "PATCH") {
        return json(
          {
            code: "CONFLICT",
            detail: "shot version conflict",
            details: { expected_version: 4, actual_version: 6 },
          },
          409,
        );
      }
      reads.push(url);
      return json({
        shot: {
          ...SHOT,
          version: 6,
          image_prompt: "server moved on",
          video_prompt: "server video prompt",
        },
      });
    });
    renderPanel();

    editImagePrompt("local draft prompt");
    fireEvent.click(screen.getByTestId("save-shot-design"));

    const conflict = await screen.findByTestId("shot-design-conflict");
    expect(conflict).toHaveTextContent("本地草稿基于 v4");
    expect(conflict).toHaveTextContent("服务器当前为 v6");
    expect(conflict).toHaveTextContent("草稿已保留");
    // The draft is untouched while the conflict is unresolved.
    expect((screen.getByLabelText("图片提示词") as HTMLTextAreaElement).value).toBe(
      "local draft prompt",
    );

    fireEvent.click(screen.getByTestId("shot-design-reload-server"));

    await waitFor(() =>
      expect((screen.getByLabelText("图片提示词") as HTMLTextAreaElement).value).toBe(
        "server moved on",
      ),
    );
    expect(screen.queryByTestId("shot-design-conflict")).not.toBeInTheDocument();
    expect(screen.getByTestId("shot-design-message")).toHaveTextContent("已载入服务器最新设计");
    expect(reads.some((url) => url.endsWith(`/shots/${SHOT.id}/workbench`))).toBe(true);
  });

  it("never marks the draft clean or adopts the response version on its own", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (init?.method === "PATCH") {
        return json({ id: SHOT.id, version: 99, image_prompt: "x", video_prompt: "y" });
      }
      return json({});
    });
    const { onSaved } = renderPanel();

    editImagePrompt("local draft prompt");
    fireEvent.click(screen.getByTestId("save-shot-design"));

    await waitFor(() =>
      expect(screen.getByTestId("shot-design-message")).toHaveTextContent("已保存设计"),
    );
    expect(onSaved).toHaveBeenCalled();
    // Only the parent's server refetch may make the draft clean: the panel must
    // not adopt the mutation response's version (99 here) as its own truth.
    expect(screen.getByTestId("shot-design-dirty")).toBeInTheDocument();
    expect(screen.queryByTestId("shot-design-saved-state")).not.toBeInTheDocument();
  });

  it("explains a non-conflict save failure without inventing a version conflict", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (init?.method === "PATCH") {
        return json(
          { code: "VALIDATION_ERROR", detail: "director_state must be a JSON object" },
          422,
        );
      }
      return json({});
    });
    renderPanel();

    editImagePrompt("local draft prompt");
    fireEvent.click(screen.getByTestId("save-shot-design"));

    await waitFor(() =>
      expect(screen.getByTestId("shot-design-message")).toHaveTextContent("保存失败"),
    );
    expect(screen.queryByTestId("shot-design-conflict")).not.toBeInTheDocument();
    expect(screen.getByTestId("shot-design-dirty")).toBeInTheDocument();
  });
});
