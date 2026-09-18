import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
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
    const options = invalidate.mock.calls[0]?.[0];
    expect(options).toEqual(expect.objectContaining({ predicate: expect.any(Function) }));
    const predicate = options && "predicate" in options ? options.predicate : undefined;
    expect(predicate?.({ queryKey: ["snapshot", "project-1"] } as never)).toBe(true);
    expect(predicate?.({ queryKey: ["snapshot", "project-2"] } as never)).toBe(false);

    view.unmount();
    expect(source?.closed).toBe(true);
  });
});
