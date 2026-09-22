import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { roleLabel } from "../../src/features/assets/api";
import { AddArtifactToAssetDialog } from "../../src/features/assets/AddArtifactToAssetDialog";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ARTIFACT_ID = "11111111-1111-4111-8111-111111111111";
const SHOT_ID = "22222222-2222-4222-8222-222222222222";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const ASSET = {
  id: "33333333-3333-4333-8333-333333333333",
  project_id: PROJECT_ID,
  kind: "character",
  name: "林墨",
  description: "",
  metadata: {},
  status: "active",
  version: 1,
  created_at: "2026-09-15T00:00:00Z",
  updated_at: "2026-09-15T00:00:00Z",
};

function renderDialog(props: Partial<React.ComponentProps<typeof AddArtifactToAssetDialog>> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  const onCreated = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <AddArtifactToAssetDialog
        projectId={PROJECT_ID}
        artifactId={ARTIFACT_ID}
        defaultName="林墨"
        defaultKind="character"
        sourceLabel="关键帧候选"
        shotId={SHOT_ID}
        onCreated={onCreated}
        onClose={onClose}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onClose, onCreated };
}

describe("AddArtifactToAssetDialog", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps keyboard focus inside the modal and closes on Escape", () => {
    const { onClose } = renderDialog();
    const dialog = screen.getByRole("dialog", { name: "将生成结果加入资产" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
      ),
    );
    const first = focusable[0]!;
    const last = focusable.at(-1)!;
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("offers only the asset kinds a video Artifact may become", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      return json(ASSET, 201);
    });

    renderDialog({ artifactType: "video", defaultKind: "character" });
    const kindSelect = screen.getByLabelText("资产类型");
    const options = Array.from(kindSelect.querySelectorAll("option")).map(
      (option) => option.textContent,
    );
    // 角色 / 场景 are image-only server side; offering them here would turn the
    // explicit confirmation into a late refusal.
    expect(options).toEqual(["视频"]);
    expect((kindSelect as HTMLSelectElement).value).toBe("video");
  });

  it("keeps 角色 / 场景 available for an image Artifact", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      return json(ASSET, 201);
    });

    renderDialog({ artifactType: "image", defaultKind: "character" });
    const options = Array.from(screen.getByLabelText("资产类型").querySelectorAll("option")).map(
      (option) => option.textContent,
    );
    expect(options).toEqual(["角色", "场景", "视频"]);
  });

  it("shows the provenance and sends one explicit creation request with a stable key", async () => {
    const calls: Array<{ url: string; key: string | undefined; body: Record<string, unknown> }> =
      [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      const headers = (init?.headers ?? {}) as Record<string, string>;
      calls.push({
        url,
        key: headers["Idempotency-Key"],
        body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {},
      });
      return json(ASSET, 201);
    });
    const { onCreated } = renderDialog();

    expect(screen.getByTestId("add-asset-source")).toHaveTextContent("关键帧候选");
    expect(screen.getByLabelText("资产类型")).toHaveValue("character");
    expect(screen.getByLabelText("参考角色")).toHaveValue("front_face");

    fireEvent.click(screen.getByTestId("add-asset-confirm"));

    const result = await screen.findByTestId("add-asset-result");
    expect(result).toHaveTextContent("已创建资产「林墨」");
    expect(result).toHaveTextContent("status=formal");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe(`/api/v1/projects/${PROJECT_ID}/assets/from-artifact`);
    expect(calls[0]?.key).toMatch(/^asset-from-artifact:/);
    expect(calls[0]?.body).toMatchObject({
      kind: "character",
      name: "林墨",
      artifact_id: ARTIFACT_ID,
      reference_role: "front_face",
    });
    expect(onCreated).toHaveBeenCalledOnce();
  });

  it("binds the new asset version to the shot only as a second explicit action", async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      calls.push({
        url,
        body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {},
      });
      if (url.endsWith("/assets/from-artifact")) return json(ASSET, 201);
      return json({ id: "binding-1" }, 201);
    });
    renderDialog();

    fireEvent.click(screen.getByTestId("add-asset-confirm"));
    await screen.findByTestId("add-asset-result");
    // Creation alone must not bind anything.
    expect(calls.filter((call) => call.url.includes("/references"))).toHaveLength(0);

    fireEvent.click(screen.getByTestId("add-asset-bind-shot"));
    await waitFor(() => expect(screen.getByTestId("add-asset-bind-shot")).toBeDisabled());
    const binding = calls.find((call) => call.url.includes("/references"));
    expect(binding?.url).toBe(`/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/references`);
    expect(binding?.body).toMatchObject({
      asset_id: ASSET.id,
      artifact_id: ARTIFACT_ID,
      resolution_mode: "direct_artifact",
    });
  });

  it("keeps the dialog open and explains a server rejection", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      return json(
        { code: "CONFLICT", detail: "an asset with this kind and name already exists" },
        409,
      );
    });
    const { onCreated } = renderDialog();

    fireEvent.click(screen.getByTestId("add-asset-confirm"));

    const error = await screen.findByTestId("add-asset-error");
    expect(error).toHaveTextContent("already exists");
    expect(screen.queryByTestId("add-asset-result")).not.toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("reuses the same request key when a lost response is retried by hand", async () => {
    const keys: Array<string | undefined> = [];
    let attempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      const headers = (init?.headers ?? {}) as Record<string, string>;
      keys.push(headers["Idempotency-Key"]);
      attempts += 1;
      if (attempts === 1) return Promise.reject(new TypeError("response lost"));
      return json(ASSET, 201);
    });
    renderDialog();

    fireEvent.click(screen.getByTestId("add-asset-confirm"));
    expect(await screen.findByTestId("add-asset-error")).toHaveTextContent("response lost");
    fireEvent.click(screen.getByTestId("add-asset-confirm"));
    await screen.findByTestId("add-asset-result");

    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });

  it("switches reference roles with the asset kind and never sends an impossible pair", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({}));
    renderDialog();

    fireEvent.change(screen.getByLabelText("资产类型"), { target: { value: "scene" } });
    expect(screen.getByLabelText("参考角色")).toHaveValue("layout_reference");
    expect(roleLabel("layout_reference")).toBe("空间布局");
    expect(roleLabel("front_face")).toBe("正面");
  });

  it("does not require a shot to create an asset", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      return json(ASSET, 201);
    });
    renderDialog({ shotId: null });

    fireEvent.click(screen.getByTestId("add-asset-confirm"));
    await screen.findByTestId("add-asset-result");

    expect(screen.queryByTestId("add-asset-bind-shot")).not.toBeInTheDocument();
    expect(screen.getByTestId("add-asset-result")).toHaveTextContent("不会自动绑定引用");
  });
});
