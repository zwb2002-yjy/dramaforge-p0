import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ProposalPreview,
  type ProposalItemData,
} from "../../src/features/director/ProposalPreview";

const items: ProposalItemData[] = [
  {
    id: "i1",
    command: "shot.update_director_state",
    suggestion: "改低机位",
    rationale: "增强张力",
    benefit: "更电影感",
    cost: "重跑关键帧",
    risk: "低",
    impact: "shot 1",
    status: "pending",
  },
  {
    id: "i2",
    command: "shot.set_model_override",
    suggestion: "换模型",
    rationale: "画质更高",
    benefit: "更好",
    cost: "重跑",
    risk: "中",
    impact: "shot 1",
    status: "pending",
  },
];

describe("ProposalPreview", () => {
  it("renders every item with fields and accept/reject", () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    render(<ProposalPreview items={items} onAccept={onAccept} onReject={onReject} />);
    expect(screen.getByText("改低机位")).toBeTruthy();
    expect(screen.getByText("增强张力")).toBeTruthy();
    expect(screen.getByText("重跑关键帧")).toBeTruthy();
    expect(screen.getAllByText("接受")).toHaveLength(2);
    fireEvent.click(screen.getAllByText("接受")[0]);
    expect(onAccept).toHaveBeenCalledWith("i1");
  });

  it("marks resolved items without controls", () => {
    const resolved = [{ ...items[0], status: "accepted" as const }];
    render(<ProposalPreview items={resolved} />);
    expect(screen.getByText("accepted")).toBeTruthy();
    expect(screen.queryByText("接受")).toBeNull();
  });
});
