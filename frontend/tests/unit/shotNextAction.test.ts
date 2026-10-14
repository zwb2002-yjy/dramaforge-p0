import { describe, expect, it } from "vitest";

import {
  defaultVideoMode,
  shotNextAction,
  type ShotNextActionInput,
} from "../../src/features/shots/shotNextAction";

const BASE: ShotNextActionInput = {
  dirty: false,
  hasFormalKeyframe: false,
  hasFormalVideo: false,
  pendingKeyframeCandidates: 0,
  pendingVideoCandidates: 0,
  keyframeStatus: null,
  videoStatus: null,
  keyframeUnknown: false,
  videoUnknown: false,
  referencesReady: true,
  videoMode: "first_frame",
  lastFrameCount: 0,
  referenceCount: 0,
  keyframeReady: true,
  videoReady: true,
  keyframeBlocker: null,
  videoBlocker: null,
};

function next(overrides: Partial<ShotNextActionInput>) {
  return shotNextAction({ ...BASE, ...overrides });
}

describe("shotNextAction", () => {
  it("saves an unsaved design before anything else", () => {
    expect(next({ dirty: true, keyframeStatus: "running" })).toEqual({ kind: "save" });
  });

  it("starts with the frame when there is no formal keyframe", () => {
    expect(next({})).toEqual({ kind: "generate_keyframe" });
  });

  it("asks to review a waiting candidate instead of generating again", () => {
    expect(next({ pendingKeyframeCandidates: 2 })).toEqual({
      kind: "review_candidate",
      stage: "image_keyframe",
    });
    expect(next({ hasFormalKeyframe: true, pendingVideoCandidates: 1 })).toEqual({
      kind: "review_candidate",
      stage: "video",
    });
  });

  it("moves to video once the formal keyframe exists", () => {
    expect(next({ hasFormalKeyframe: true })).toEqual({ kind: "generate_video" });
  });

  it("reports completion once the formal video exists", () => {
    expect(next({ hasFormalKeyframe: true, hasFormalVideo: true })).toEqual({
      kind: "complete",
    });
  });

  it("never offers a primary resubmission while a stage runs", () => {
    expect(next({ keyframeStatus: "queued" })).toEqual({
      kind: "running",
      stage: "image_keyframe",
      status: "queued",
    });
    expect(next({ hasFormalKeyframe: true, videoStatus: "running" })).toEqual({
      kind: "running",
      stage: "video",
      status: "running",
    });
  });

  it("reports an unknown submission instead of guessing", () => {
    expect(next({ keyframeUnknown: true, keyframeStatus: "running" })).toEqual({
      kind: "unknown",
      stage: "image_keyframe",
    });
    expect(next({ hasFormalKeyframe: true, videoUnknown: true })).toEqual({
      kind: "unknown",
      stage: "video",
    });
  });

  it("names the blocker when the model or inputs are not ready", () => {
    expect(next({ keyframeReady: false, keyframeBlocker: "MODEL_BINDING_MISSING" })).toEqual({
      kind: "blocked",
      stage: "image_keyframe",
      reason: "MODEL_BINDING_MISSING",
    });
    expect(next({ referencesReady: false })).toEqual({
      kind: "blocked",
      stage: "image_keyframe",
      reason: "REFERENCES_RESOLVING",
    });
    expect(next({ videoMode: "omni_reference" })).toEqual({
      kind: "blocked",
      stage: "video",
      reason: "REFERENCE_REQUIRED",
    });
  });

  it("lets modes that do not start from a frame go straight to video", () => {
    expect(next({ videoMode: "text_to_video", referencesReady: false })).toEqual({
      kind: "generate_video",
    });
    expect(next({ videoMode: "last_frame", lastFrameCount: 1 })).toEqual({
      kind: "generate_video",
    });
  });
});

describe("defaultVideoMode", () => {
  it("starts from the formal frame and closes on a single saved last frame", () => {
    expect(defaultVideoMode({ hasFormalKeyframe: false, lastFrameCount: 1 })).toBe("first_frame");
    expect(defaultVideoMode({ hasFormalKeyframe: true, lastFrameCount: 0 })).toBe("first_frame");
    expect(defaultVideoMode({ hasFormalKeyframe: true, lastFrameCount: 1 })).toBe(
      "first_last_frame",
    );
  });
});
