/**
 * The single primary action of the selected Shot, derived only from saved
 * server facts plus the local "unsaved design" flag. It never invents
 * progress: running and unknown submissions are reported as they are, so the
 * primary button can never become a blind retry of a possibly billed call.
 */

export type ShotVideoMode =
  "first_frame" | "last_frame" | "first_last_frame" | "text_to_video" | "omni_reference";

export type ShotNextAction =
  | { kind: "save" }
  | { kind: "unknown"; stage: "image_keyframe" | "video" }
  | { kind: "running"; stage: "image_keyframe" | "video"; status: string }
  | { kind: "review_candidate"; stage: "image_keyframe" | "video" }
  | { kind: "generate_keyframe" }
  | { kind: "generate_video" }
  | { kind: "complete" }
  | { kind: "blocked"; stage: "image_keyframe" | "video"; reason: string };

export type ShotNextActionInput = {
  dirty: boolean;
  hasFormalKeyframe: boolean;
  hasFormalVideo: boolean;
  /** Completed, available, not-rejected candidates per stage. */
  pendingKeyframeCandidates: number;
  pendingVideoCandidates: number;
  keyframeStatus: string | null;
  videoStatus: string | null;
  keyframeUnknown: boolean;
  videoUnknown: boolean;
  referencesReady: boolean;
  videoMode: ShotVideoMode;
  /** Mode-specific inputs; see the video mode contracts. */
  lastFrameCount: number;
  referenceCount: number;
  keyframeReady: boolean;
  videoReady: boolean;
  /** Preflight reason when a stage cannot execute; null while loading. */
  keyframeBlocker: string | null;
  videoBlocker: string | null;
};

/** Video modes that do not start from the formal keyframe. */
export function videoModeNeedsKeyframe(mode: ShotVideoMode): boolean {
  return mode === "first_frame" || mode === "first_last_frame";
}

/** Why the chosen video mode cannot run yet, independent of the model. */
export function videoInputBlocker(input: ShotNextActionInput): string | null {
  if (videoModeNeedsKeyframe(input.videoMode) && !input.hasFormalKeyframe) {
    return "FORMAL_KEYFRAME_REQUIRED";
  }
  if (
    (input.videoMode === "last_frame" || input.videoMode === "first_last_frame") &&
    input.lastFrameCount !== 1
  ) {
    return "LAST_FRAME_REFERENCE_REQUIRED";
  }
  if (input.videoMode === "omni_reference" && input.referenceCount === 0) {
    return "REFERENCE_REQUIRED";
  }
  if (input.videoMode !== "text_to_video" && !input.referencesReady) {
    return "REFERENCES_RESOLVING";
  }
  return null;
}

export function shotNextAction(input: ShotNextActionInput): ShotNextAction {
  if (input.dirty) return { kind: "save" };
  if (input.keyframeUnknown) return { kind: "unknown", stage: "image_keyframe" };
  if (input.videoUnknown) return { kind: "unknown", stage: "video" };
  if (input.keyframeStatus)
    return { kind: "running", stage: "image_keyframe", status: input.keyframeStatus };
  if (input.videoStatus) return { kind: "running", stage: "video", status: input.videoStatus };

  const videoFirst = !videoModeNeedsKeyframe(input.videoMode);
  if (input.hasFormalVideo) {
    return input.pendingVideoCandidates > 0
      ? { kind: "review_candidate", stage: "video" }
      : { kind: "complete" };
  }
  if (!input.hasFormalKeyframe && !videoFirst) {
    if (input.pendingKeyframeCandidates > 0) {
      return { kind: "review_candidate", stage: "image_keyframe" };
    }
    if (!input.referencesReady) {
      return { kind: "blocked", stage: "image_keyframe", reason: "REFERENCES_RESOLVING" };
    }
    if (!input.keyframeReady) {
      return {
        kind: "blocked",
        stage: "image_keyframe",
        reason: input.keyframeBlocker ?? "PREFLIGHT_PENDING",
      };
    }
    return { kind: "generate_keyframe" };
  }
  if (input.pendingVideoCandidates > 0) return { kind: "review_candidate", stage: "video" };
  const inputBlocker = videoInputBlocker(input);
  if (inputBlocker) return { kind: "blocked", stage: "video", reason: inputBlocker };
  if (!input.videoReady) {
    return { kind: "blocked", stage: "video", reason: input.videoBlocker ?? "PREFLIGHT_PENDING" };
  }
  return { kind: "generate_video" };
}

/**
 * The video mode a creator would expect from saved facts alone: start from the
 * formal frame, and close on a saved last frame when exactly one exists. Other
 * modes stay an explicit choice under 「更多设置」.
 */
export function defaultVideoMode(input: {
  hasFormalKeyframe: boolean;
  lastFrameCount: number;
}): ShotVideoMode {
  return input.hasFormalKeyframe && input.lastFrameCount === 1 ? "first_last_frame" : "first_frame";
}

export const VIDEO_MODE_LABEL: Record<ShotVideoMode, string> = {
  first_frame: "正式画面作为首帧",
  first_last_frame: "正式画面 + 尾帧",
  last_frame: "尾帧生成",
  text_to_video: "仅用文字",
  omni_reference: "参考素材生成",
};

export const NEXT_ACTION_BLOCKER_LABEL: Record<string, string> = {
  FORMAL_KEYFRAME_REQUIRED: "需要先确定正式画面",
  LAST_FRAME_REFERENCE_REQUIRED: "需要一条尾帧参考",
  REFERENCE_REQUIRED: "需要至少一条参考素材",
  REFERENCES_RESOLVING: "正在读取参考素材…",
  PREFLIGHT_PENDING: "正在确认模型…",
};
