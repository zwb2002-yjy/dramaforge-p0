import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DirectorBoard2D, type BoardElement } from "../../src/features/director/DirectorBoard2D";

const elements: BoardElement[] = [
  { kind: "character", name: "林墨", x: 0.3, y: 0.5, orientation: 90 },
  { kind: "camera", name: "A", x: 0.8, y: 0.4 },
  { kind: "object", name: "桌子", x: 0.5, y: 0.6 },
];

describe("DirectorBoard2D", () => {
  it("renders characters, cameras and objects with composition bounds", () => {
    render(
      <DirectorBoard2D
        elements={elements}
        compositionBounds={{ x: 0.1, y: 0.1, width: 0.8, height: 0.8 }}
      />,
    );
    expect(screen.getAllByTestId("board-character")).toHaveLength(1);
    expect(screen.getAllByTestId("board-camera")).toHaveLength(1);
    expect(screen.getAllByTestId("board-object")).toHaveLength(1);
    expect(screen.getByTestId("composition-bounds")).toBeTruthy();
    expect(screen.getByText("林墨")).toBeTruthy();
  });

  it("emits a new camera on canvas click", () => {
    const onChange = vi.fn();
    render(<DirectorBoard2D elements={elements} onChange={onChange} />);
    const svg = screen.getByTestId("director-board-2d");
    Object.defineProperty(svg, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 600, height: 400 }),
      configurable: true,
    });
    fireEvent.click(svg, { clientX: 300, clientY: 200 });
    expect(onChange).toHaveBeenCalled();
    const next = onChange.mock.calls[0][0] as BoardElement[];
    expect(next[next.length - 1].kind).toBe("camera");
  });
});
