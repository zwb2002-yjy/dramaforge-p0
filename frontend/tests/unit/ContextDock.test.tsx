import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContextDock } from "../../src/features/shots/ContextDock";

describe("ContextDock", () => {
  it("exposes Character / Camera / Motion / Look / Generate / Director / Takes / Details", () => {
    render(
      <ContextDock
        activeTool={null}
        candidateCount={2}
        trayExpanded={false}
        detailsOpen={false}
        hasShot
        onSelectTool={vi.fn()}
        onToggleTray={vi.fn()}
        onToggleDetails={vi.fn()}
      />,
    );

    expect(screen.getByTestId("context-dock")).toBeInTheDocument();
    expect(screen.getByTestId("context-dock-character")).toHaveTextContent("角色");
    expect(screen.getByTestId("context-dock-camera")).toHaveTextContent("机位");
    expect(screen.getByTestId("context-dock-motion")).toHaveTextContent("运动");
    expect(screen.getByTestId("context-dock-look")).toHaveTextContent("画面");
    expect(screen.getByTestId("context-dock-generate")).toHaveTextContent("生成");
    expect(screen.getByTestId("context-dock-director")).toHaveTextContent("导演");
    expect(screen.getByTestId("context-dock-takes")).toHaveTextContent("Takes · 2");
    expect(screen.getByTestId("context-dock-takes")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("context-dock-details")).toHaveTextContent("详情");
    expect(screen.getByTestId("context-dock-details")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("context-dock-design")).not.toBeInTheDocument();
    expect(screen.queryByTestId("context-dock-references")).not.toBeInTheDocument();
  });

  it("marks the active tool and disabled state from props", () => {
    const onSelectTool = vi.fn();
    const { rerender } = render(
      <ContextDock
        activeTool="generate"
        candidateCount={0}
        trayExpanded
        detailsOpen
        hasShot
        onSelectTool={onSelectTool}
        onToggleTray={vi.fn()}
        onToggleDetails={vi.fn()}
      />,
    );

    expect(screen.getByTestId("context-dock-generate")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("context-dock-character"));
    expect(onSelectTool).toHaveBeenCalledWith("character");
    fireEvent.click(screen.getByTestId("context-dock-camera"));
    expect(onSelectTool).toHaveBeenCalledWith("camera");
    fireEvent.click(screen.getByTestId("context-dock-director"));
    expect(onSelectTool).toHaveBeenCalledWith("director");

    rerender(
      <ContextDock
        activeTool={null}
        candidateCount={0}
        trayExpanded={false}
        detailsOpen={false}
        hasShot={false}
        onSelectTool={onSelectTool}
        onToggleTray={vi.fn()}
        onToggleDetails={vi.fn()}
      />,
    );
    expect(screen.getByTestId("context-dock-look")).toBeDisabled();
    expect(screen.getByTestId("context-dock-takes")).toBeDisabled();
    expect(screen.getByTestId("context-dock-details")).toBeDisabled();
  });

  it("toggles the candidate tray and details from the dock", () => {
    const onToggleTray = vi.fn();
    const onToggleDetails = vi.fn();
    render(
      <ContextDock
        activeTool={null}
        candidateCount={1}
        trayExpanded={false}
        detailsOpen={false}
        hasShot
        onSelectTool={vi.fn()}
        onToggleTray={onToggleTray}
        onToggleDetails={onToggleDetails}
      />,
    );

    fireEvent.click(screen.getByTestId("context-dock-takes"));
    fireEvent.click(screen.getByTestId("context-dock-details"));
    expect(onToggleTray).toHaveBeenCalledTimes(1);
    expect(onToggleDetails).toHaveBeenCalledTimes(1);
  });
});
