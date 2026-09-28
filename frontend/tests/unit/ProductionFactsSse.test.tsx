import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProductionFactsSse } from "../../src/components/sse/ProductionFactsSse";

type Listener = (event: Event) => void;

class FakeEventSource {
  static readonly instances: FakeEventSource[] = [];
  readonly url: string;
  readonly withCredentials: boolean;
  private readonly listeners = new Map<string, Set<Listener>>();
  closed = false;

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const callback =
      typeof listener === "function" ? listener : (event: Event) => listener.handleEvent(event);
    const listeners = this.listeners.get(type) ?? new Set<Listener>();
    listeners.add(callback);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const callback =
      typeof listener === "function" ? listener : (event: Event) => listener.handleEvent(event);
    this.listeners.get(type)?.delete(callback);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data: string): void {
    const event = new MessageEvent(type, { data });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

describe("ProductionFactsSse", () => {
  beforeEach(() => {
    FakeEventSource.instances.length = 0;
    Object.defineProperty(globalThis, "EventSource", {
      configurable: true,
      value: FakeEventSource,
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("subscribes with workspace scope and invalidates queries for the event project", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ProductionFactsSse workspaceId="workspace-1" />
      </QueryClientProvider>,
    );

    const source = FakeEventSource.instances[0];
    expect(source?.url).toBe("/api/v1/events/stream?workspace_id=workspace-1");
    expect(source?.withCredentials).toBe(true);

    source?.emit(
      "production.facts.v1",
      JSON.stringify({
        topic: "production.facts.v1",
        project_id: "project-1",
        payload: { project_id: "project-1" },
      }),
    );

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1));
    expect(invalidate.mock.calls[0]?.[1]).toEqual({ cancelRefetch: false });
    const options = invalidate.mock.calls[0]?.[0];
    expect(options).toEqual(expect.objectContaining({ predicate: expect.any(Function) }));
    const predicate = options && "predicate" in options ? options.predicate : undefined;
    expect(predicate?.({ queryKey: ["snapshot", "project-1"] } as never)).toBe(true);
    expect(predicate?.({ queryKey: ["snapshot", "project-2"] } as never)).toBe(false);

    view.unmount();
    expect(source?.closed).toBe(true);
  });
  it("coalesces bursts and does not refresh settings, scripts, drafts or another shot", async () => {
    const client = new QueryClient();
    const entries = [
      ["production-summary", "p1"],
      ["project-model-profile", "p1"],
      ["script-workspace", "p1"],
      ["edit-session", "p1", "cut"],
      ["shot-workbench", "p1", "s1"],
      ["shot-workbench", "p1", "s2"],
      ["production-summary", "p2"],
    ];
    for (const key of entries) client.setQueryData(key, {});
    client.setQueryData(["scene-workspace", "p1", "scene1"], { shots: [{ id: "s1" }] });
    client.setQueryData(["scene-workspace", "p1", "scene2"], { shots: [{ id: "s2" }] });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(
      <QueryClientProvider client={client}>
        <ProductionFactsSse workspaceId="w1" />
      </QueryClientProvider>,
    );
    const source = FakeEventSource.instances[0]!;
    act(() => {
      for (let index = 0; index < 50; index++)
        source.emit(
          "production.facts.v1",
          JSON.stringify({
            topic: "production.facts.v1",
            workspace_id: "w1",
            project_id: "p1",
            payload: { project_id: "p1", notice: { kind: "execution_changed", shot_id: "s1" } },
          }),
        );
    });
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1));
    for (const key of [entries[0], entries[4], ["scene-workspace", "p1", "scene1"]]) {
      expect(client.getQueryState(key!)?.isInvalidated).toBe(true);
    }
    for (const key of [
      entries[1],
      entries[2],
      entries[3],
      entries[5],
      entries[6],
      ["scene-workspace", "p1", "scene2"],
    ]) {
      expect(client.getQueryState(key!)?.isInvalidated).toBe(false);
    }
  });

  it("invalidates formal projections only when Formal actually changes", async () => {
    const client = new QueryClient();
    const key = ["opencut-manifest", "p1"];
    client.setQueryData(key, {});
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(
      <QueryClientProvider client={client}>
        <ProductionFactsSse workspaceId="w1" />
      </QueryClientProvider>,
    );
    const source = FakeEventSource.instances[0]!;
    const emit = (kind: string) =>
      source.emit(
        "production.facts.v1",
        JSON.stringify({
          topic: "production.facts.v1",
          project_id: "p1",
          payload: { notice: { kind, shot_id: "s1" } },
        }),
      );
    emit("execution_changed");
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1));
    expect(client.getQueryState(key)?.isInvalidated).toBe(false);
    emit("formal_selected");
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it("discards pending notices on a workspace switch and ignores invalid envelopes", async () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const view = (id: string) => (
      <QueryClientProvider client={client}>
        <ProductionFactsSse workspaceId={id} />
      </QueryClientProvider>
    );
    const rendered = render(view("w1"));
    const old = FakeEventSource.instances[0]!;
    old.emit(
      "production.facts.v1",
      JSON.stringify({ topic: "production.facts.v1", project_id: "p1" }),
    );
    rendered.rerender(view("w2"));
    const current = FakeEventSource.instances[1]!;
    current.emit("production.facts.v1", "bad-json");
    current.emit(
      "production.facts.v1",
      JSON.stringify({
        topic: "production.facts.v1",
        workspace_id: "w1",
        project_id: "p1",
      }),
    );
    current.emit(
      "production.facts.v1",
      JSON.stringify({
        topic: "production.facts.v1",
        project_id: "p1",
        payload: { project_id: "p2" },
      }),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 200));
    });
    expect(old.closed).toBe(true);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
