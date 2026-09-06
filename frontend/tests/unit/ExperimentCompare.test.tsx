import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ExperimentCompare,
  type ExperimentColumnData,
} from "../../src/features/experiments/ExperimentCompare";

const formal: ExperimentColumnData = {
  label: "正式",
  model: "video-model-a",
  imageArtifactUrl: "/artifacts/formal-kf",
  videoArtifactUrl: "/artifacts/formal-video",
  prompt: "formal prompt",
  translationWarning: null,
  references: [{ purpose: "identity", delivery: "exact" }],
};

const experimentA: ExperimentColumnData = {
  label: "实验 A",
  model: "video-model-b",
  imageArtifactUrl: "/artifacts/exp-a-kf",
  videoArtifactUrl: null,
  prompt: "formal prompt",
  translationWarning: "camera_language 以近似方式传递",
  references: [{ purpose: "identity", delivery: "exact" }],
};

describe("ExperimentCompare", () => {
  it("renders formal + experiment columns and compare rows", () => {
    render(<ExperimentCompare formal={formal} experiments={[experimentA]} />);
    expect(screen.getByText("正式")).toBeTruthy();
    expect(screen.getByText("实验 A")).toBeTruthy();
    expect(screen.getByText("video-model-a")).toBeTruthy();
    expect(screen.getByText("video-model-b")).toBeTruthy();
    expect(screen.getByText("camera_language 以近似方式传递")).toBeTruthy();
    expect(screen.getAllByText(/identity/).length).toBeGreaterThan(0);
  });

  it("renders placeholder for missing media and shows no warning when clean", () => {
    render(<ExperimentCompare formal={formal} experiments={[experimentA]} />);
    // formal has no translation warning -> 无
    expect(screen.getAllByText("无").length).toBeGreaterThan(0);
  });

  it("renders an empty state without experiments", () => {
    render(<ExperimentCompare formal={formal} experiments={[]} />);
    expect(screen.getByTestId("experiment-compare")).toBeTruthy();
    expect(screen.getByText("正式")).toBeTruthy();
  });
});
