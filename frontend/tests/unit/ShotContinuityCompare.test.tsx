import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShotContinuityCompare } from "../../src/features/shots/ShotContinuityCompare";
import type { ShotLite } from "../../src/features/shots/api";
import type { ShotCandidate } from "../../src/features/shots/shotCandidates";
import * as apiModule from "../../src/features/review/annotationApi";

const mockShots: ShotLite[] = [
  {
    id: "shot-1",
    project_id: "p1",
    scene_id: "scene-1",
    shot_number: 1,
    shot_type: "中景",
    camera_move: "固定",
    visual_description: "主角在书房阅读，穿浅蓝色衬衫",
    dialogue: "这封信写的是真的吗？",
    duration_seconds: "3.5",
    status: "completed",
    sort_order: 1,
    version: 1,
    director_state: {},
    image_prompt: "A man reading a letter in study room",
    video_prompt: "Static shot of man reading",
    formal_keyframe_artifact_id: "art-kf-1",
    formal_video_artifact_id: "art-vid-1",
    formal_composite_artifact_id: null,
  },
  {
    id: "shot-2",
    project_id: "p1",
    scene_id: "scene-1",
    shot_number: 2,
    shot_type: "特写",
    camera_move: "推镜头",
    visual_description: "主角神色惊疑，信纸特写",
    dialogue: "怎么会是这样...",
    duration_seconds: "4.0",
    status: "completed",
    sort_order: 2,
    version: 1,
    director_state: {},
    image_prompt: "Close up of man looking shocked",
    video_prompt: "Slow push in on man",
    formal_keyframe_artifact_id: "art-kf-2",
    formal_video_artifact_id: null, // Only keyframe
    formal_composite_artifact_id: null,
  },
  {
    id: "shot-3",
    project_id: "p1",
    scene_id: "scene-1",
    shot_number: 3,
    shot_type: "全景",
    camera_move: "摇镜头",
    visual_description: "门突然被推开，仆人匆忙走入",
    dialogue: "老爷，外面有人求见！",
    duration_seconds: "3.0",
    status: "completed",
    sort_order: 3,
    version: 1,
    director_state: {},
    image_prompt: "Door opening suddenly",
    video_prompt: "Pan from door to room",
    formal_keyframe_artifact_id: "art-kf-3",
    formal_video_artifact_id: "art-vid-3",
    formal_composite_artifact_id: null,
  },
];

const mockBindings = [
  {
    id: "bind-1",
    purpose: "character_reference",
    label: "主角（常服）",
    asset_id: "asset-hero",
    asset_version_id: "v-hero-blue-shirt",
    artifact_id: "art-hero-ref",
    resolution_mode: "current_formal",
    stage: "image_keyframe",
    version: 1,
  },
];

const mockCandidate: ShotCandidate = {
  artifactId: "art-candidate-video-2",
  artifactType: "video",
  stage: "video",
  status: "completed",
  nodeRunId: "run-video-201",
  nodeKey: "video_generation",
  mimeType: "video/mp4",
  storageState: "available",
  createdAt: "2026-10-20T12:00:00Z",
  reviewAllowed: true,
  reviewDecision: null,
  reviewBlockedReason: null,
  reviewNodeRunId: null,
  contentHash: "hash-candidate-2",
  duplicateContent: false,
};

describe("ShotContinuityCompare", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders four zones (prev end, bindings, current candidate, next start) and narrative comparison", () => {
    render(
      <ShotContinuityCompare
        projectId="p1"
        shots={mockShots}
        shotId="shot-2"
        candidate={mockCandidate}
        bindings={mockBindings}
      />,
    );

    // Click toggle button to open comparison
    const toggleBtn = screen.getByRole("button", { name: "相邻镜头对照" });
    fireEvent.click(toggleBtn);

    // 1. Four Zones Check
    expect(screen.getByTestId("shot-continuity-grid")).toBeInTheDocument();
    expect(screen.getByLabelText("前镜末帧")).toBeInTheDocument();
    expect(screen.getByLabelText("当前镜头绑定参考")).toBeInTheDocument();
    expect(screen.getByLabelText("当前镜头首帧")).toBeInTheDocument();
    expect(screen.getByLabelText("后镜首帧")).toBeInTheDocument();

    // Check bound reference item
    expect(screen.getByTestId("continuity-bindings-list")).toBeInTheDocument();
    expect(screen.getByText("主角（常服）")).toBeInTheDocument();
    expect(screen.getByText(/v-hero-blue-shirt/)).toBeInTheDocument();

    // Check candidate lineage details on current shot
    expect(screen.getByText(/NodeRun: run-vide/)).toBeInTheDocument();

    // 2. Narrative Comparison Check
    expect(screen.getByTestId("shot-continuity-narrative")).toBeInTheDocument();
    expect(screen.getByText("这封信写的是真的吗？")).toBeInTheDocument();
    expect(screen.getByText("怎么会是这样...")).toBeInTheDocument();
    expect(screen.getByText("老爷，外面有人求见！")).toBeInTheDocument();
  });

  it("resets 5-item checklist when switching candidate, and disables record button until an issue is found", () => {
    const { rerender } = render(
      <ShotContinuityCompare
        projectId="p1"
        shots={mockShots}
        shotId="shot-2"
        candidate={mockCandidate}
        bindings={mockBindings}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "相邻镜头对照" }));

    // Verify all 5 checklist items exist
    expect(screen.getByTestId("checklist-row-styling")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-row-costume_prop")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-row-spatial_axis")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-row-action_match")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-row-dialogue_emotion")).toBeInTheDocument();

    // Record button should be disabled when all are unchecked
    expect(screen.getByTestId("open-record-issue-button")).toBeDisabled();

    // Mark costume_prop as "发现问题"
    const costumeRow = screen.getByTestId("checklist-row-costume_prop");
    const costumeIssueRadio = costumeRow.querySelector(
      'input[value="issue_found"]',
    ) as HTMLInputElement;
    fireEvent.click(costumeIssueRadio);

    // Now record button is enabled
    expect(screen.getByTestId("open-record-issue-button")).not.toBeDisabled();

    // Rerender with a DIFFERENT candidate (e.g. candidate with different artifactId)
    const newCandidate: ShotCandidate = {
      ...mockCandidate,
      artifactId: "art-candidate-video-new",
      nodeRunId: "run-video-202",
    };

    rerender(
      <ShotContinuityCompare
        projectId="p1"
        shots={mockShots}
        shotId="shot-2"
        candidate={newCandidate}
        bindings={mockBindings}
      />,
    );

    // Checklist MUST be reset back to unchecked; recordBtn must become disabled again
    expect(screen.getByTestId("open-record-issue-button")).toBeDisabled();
    const resetCostumeIssueRadio = costumeRow.querySelector(
      'input[value="issue_found"]',
    ) as HTMLInputElement;
    expect(resetCostumeIssueRadio.checked).toBe(false);
  });

  it("submits continuity annotation to review API, shows review board link and repair scope guidance", async () => {
    const createAnnotationSpy = vi.spyOn(apiModule, "createReviewAnnotation").mockResolvedValue({
      id: "anno-001",
      shot_id: "shot-2",
      artifact_id: "art-candidate-video-2",
      target_kind: "video_time",
      time_start: "1.2",
      time_end: null,
      x: null,
      y: null,
      width: null,
      height: null,
      note: "[连续性问题: 服装道具] 衣服颜色与参考不一致",
      severity: "blocker",
      status: "open",
      resolved_at: null,
      created_by: "user-1",
      created_at: "2026-10-20T12:05:00Z",
    });

    render(
      <ShotContinuityCompare
        projectId="p1"
        shots={mockShots}
        shotId="shot-2"
        candidate={mockCandidate}
        bindings={mockBindings}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "相邻镜头对照" }));

    // Mark costume_prop as issue
    const costumeRow = screen.getByTestId("checklist-row-costume_prop");
    const costumeIssueRadio = costumeRow.querySelector(
      'input[value="issue_found"]',
    ) as HTMLInputElement;
    fireEvent.click(costumeIssueRadio);

    // Click record button to open issue form
    const recordBtn = screen.getByTestId("open-record-issue-button");
    fireEvent.click(recordBtn);

    expect(screen.getByTestId("continuity-issue-form")).toBeInTheDocument();
    expect(screen.getByText("art-candidate-video-2")).toBeInTheDocument();

    // Timecode input for video candidate
    const timeInput = screen.getByTestId("continuity-timecode-input");
    fireEvent.change(timeInput, { target: { value: "1.2" } });

    // Type note
    const noteInput = screen.getByTestId("continuity-issue-note-input");
    fireEvent.change(noteInput, { target: { value: "衣服颜色与参考不一致" } });

    // Click submit
    const submitBtn = screen.getByTestId("submit-continuity-annotation");
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createAnnotationSpy).toHaveBeenCalledWith(
        "p1",
        "shot-2",
        expect.objectContaining({
          artifact_id: "art-candidate-video-2",
          target_kind: "video_time",
          time_start: "1.2",
          severity: "blocker",
          note: expect.stringContaining("服装道具"),
        }),
      );
    });

    // Success banner & review board link
    expect(screen.getByTestId("continuity-annotation-success")).toBeInTheDocument();
    const reviewLink = screen.getByTestId("goto-review-board-link");
    expect(reviewLink).toBeInTheDocument();
    expect(reviewLink.getAttribute("href")).toContain("/projects/p1/review");

    // Repair scope information is displayed
    expect(screen.getByText(/修复范围由模型能力决定/)).toBeInTheDocument();
    expect(screen.getByText(/显式确认原则/)).toBeInTheDocument();
  });
});
