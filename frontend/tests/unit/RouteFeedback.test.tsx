import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  RouteFailure,
  RouteMissing,
  RoutePending,
} from "../../src/components/routing/RouteFeedback";

function open(path: string, loader: () => unknown = () => undefined) {
  const root = createRootRoute({ component: Outlet });
  const page = createRoute({
    getParentRoute: () => root,
    path: "/page",
    loader,
    component: () => <p>页面已打开</p>,
  });
  const router = createRouter({
    routeTree: root.addChildren([page]),
    history: createMemoryHistory({ initialEntries: [path] }),
    defaultPendingComponent: RoutePending,
    defaultErrorComponent: RouteFailure,
    defaultNotFoundComponent: RouteMissing,
    defaultPendingMs: 0,
    defaultPendingMinMs: 0,
  });
  render(<RouterProvider router={router} />);
}

describe("Chinese route recovery", () => {
  it("provides a route out of an unknown URL", async () => {
    open("/missing");
    expect(await screen.findByRole("heading", { name: "找不到这个页面" })).toBeVisible();
    expect(screen.getByRole("link", { name: "返回项目列表" })).toHaveAttribute("href", "/");
  });

  it("retries a failed loader without disclosing its internal error", async () => {
    let failed = true;
    open("/page", () => {
      if (failed) throw new Error("internal signed-url secret");
    });
    expect(await screen.findByTestId("route-error")).not.toHaveTextContent("signed-url");
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("页面已打开")).toBeVisible();
  });

  it("announces a pending loader then opens its page", async () => {
    let ready!: () => void;
    const pending = new Promise<void>((resolve) => {
      ready = resolve;
    });
    open("/page", () => pending);
    expect(await screen.findByRole("status")).toHaveTextContent("正在打开页面");
    ready();
    expect(await screen.findByText("页面已打开")).toBeVisible();
  });
});
