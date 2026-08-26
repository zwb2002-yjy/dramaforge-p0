import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetMentionInput } from "../../src/components/assets/AssetMentionInput";

function renderInput(projectId = "project-1") {
  const queryClient = new QueryClient();
  const onChange = vi.fn();
  const onCreateBinding = vi.fn();
  function Harness() {
    const [value, setValue] = useState("");
    return (
      <AssetMentionInput
        projectId={projectId}
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
        onCreateBinding={onCreateBinding}
      />
    );
  }
  render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
  return { onChange, onCreateBinding };
}

function json(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockAssets() {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/assets")) {
      return json([
        {
          id: "asset-linmo",
          project_id: "project-1",
          kind: "character",
          name: "林墨",
          description: "",
          metadata: {},
          status: "active",
          version: 1,
          created_at: "",
          updated_at: "",
        },
        {
          id: "asset-raincoat",
          project_id: "project-1",
          kind: "costume",
          name: "黑色雨衣",
          description: "",
          metadata: {},
          status: "active",
          version: 1,
          created_at: "",
          updated_at: "",
        },
      ]);
    }
    return json({});
  });
}

describe("AssetMentionInput", () => {
  it("shows autocomplete suggestions when typing an @ mention", async () => {
    mockAssets();
    renderInput();
    const input = screen.getByRole("textbox", { name: "提示词（@ 引用资产）" });
    fireEvent.change(input, { target: { value: "角色 @林" } });
    const options = await screen.findByTestId("mention-options");
    expect(options).toBeInTheDocument();
    expect(screen.getByText("林墨")).toBeInTheDocument();
  });

  it("selecting a suggestion creates a binding and clears the unresolved marker", async () => {
    mockAssets();
    const { onCreateBinding } = renderInput();
    const input = screen.getByRole("textbox", { name: "提示词（@ 引用资产）" });
    fireEvent.change(input, { target: { value: "角色 @林" } });
    const option = (await screen.findAllByRole("option"))[0];
    fireEvent.mouseDown(option);
    await waitFor(() =>
      expect(onCreateBinding).toHaveBeenCalledWith("@林墨", "asset-linmo", "identity"),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("mention-unresolved")).not.toBeInTheDocument(),
    );
  });

  it("marks unbound @text as unresolved without creating a binding", async () => {
    mockAssets();
    const { onCreateBinding } = renderInput();
    const input = screen.getByRole("textbox", { name: "提示词（@ 引用资产）" });
    fireEvent.change(input, { target: { value: "角色 @不存在的人" } });
    const marker = await screen.findByTestId("mention-unresolved");
    expect(marker).toHaveTextContent("未解析引用：@不存在的人");
    expect(onCreateBinding).not.toHaveBeenCalled();
  });
});

afterEach(() => vi.restoreAllMocks());
