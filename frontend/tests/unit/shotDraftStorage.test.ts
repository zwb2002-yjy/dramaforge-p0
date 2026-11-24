import { describe, expect, it, beforeEach } from "vitest";
import {
  saveShotDraft,
  loadShotDraft,
  clearShotDraft,
  detectDraftConflicts,
  restoreShotDraft,
  shotDraftFromServer,
  type StoredShotDraft,
} from "../../src/features/shots/shotDraftStorage";
import type { ShotLite } from "../../src/features/shots/api";

const mockShot: ShotLite = {
  id: "shot-123",
  project_id: "p1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "wide",
  camera_move: "pan",
  duration_seconds: "4.0",
  status: "draft",
  sort_order: 1,
  version: 2,
  image_prompt: "server image prompt",
  video_prompt: "server video prompt",
  dialogue: "server dialogue",
  visual_description: "desk scene",
  director_state: {},
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

describe("shotDraftStorage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("saves and loads shot draft scoped to project and shot", () => {
    const draft = {
      image_prompt: "local image edit",
      video_prompt: "local video edit",
      director_state: { camera: "close_up" },
    };

    const saved = saveShotDraft("proj-1", "shot-123", 2, draft);
    expect(saved).toBe(true);

    const loaded = loadShotDraft("proj-1", "shot-123");
    expect(loaded).not.toBeNull();
    expect(loaded?.projectId).toBe("proj-1");
    expect(loaded?.shotId).toBe("shot-123");
    expect(loaded?.baselineVersion).toBe(2);
    expect(loaded?.draft.image_prompt).toBe("local image edit");

    // Different shot or project returns null
    expect(loadShotDraft("proj-1", "other-shot")).toBeNull();
    expect(loadShotDraft("other-proj", "shot-123")).toBeNull();
  });

  it("clears shot draft on demand", () => {
    saveShotDraft("proj-1", "shot-123", 1, {
      image_prompt: "test",
      video_prompt: "test",
      director_state: {},
    });
    expect(loadShotDraft("proj-1", "shot-123")).not.toBeNull();

    clearShotDraft("proj-1", "shot-123");
    expect(loadShotDraft("proj-1", "shot-123")).toBeNull();
  });

  it("detects clean recovery when server version matches baseline", () => {
    const stored: StoredShotDraft = {
      projectId: "proj-1",
      shotId: "shot-123",
      baselineVersion: 2,
      draft: {
        image_prompt: "unsaved local edit",
        video_prompt: "server video prompt",
        director_state: {},
      },
      updatedAt: new Date().toISOString(),
    };

    const result = detectDraftConflicts(mockShot, stored);
    expect(result.hasConflict).toBe(false);
    expect(result.conflicts).toHaveLength(0);
  });

  it("detects field conflicts when server version advanced with different content", () => {
    const stored: StoredShotDraft = {
      projectId: "proj-1",
      shotId: "shot-123",
      baselineVersion: 1, // older baseline
      draft: {
        image_prompt: "local draft on v1",
        video_prompt: "server video prompt", // same as v2 server
        dialogue: "local dialogue on v1", // different from v2 server
        director_state: {},
      },
      updatedAt: new Date().toISOString(),
    };

    const result = detectDraftConflicts(mockShot, stored);
    expect(result.hasConflict).toBe(true);
    expect(result.conflicts.map((c) => c.field)).toEqual(["image_prompt", "dialogue"]);
    expect(result.conflicts[0].localValue).toBe("local draft on v1");
    expect(result.conflicts[0].serverValue).toBe("server image prompt");
  });

  it("detects generation settings conflicts when server version advanced with new settings", () => {
    const serverShotWithGen: ShotLite = {
      ...mockShot,
      version: 3,
      director_state: {
        generation_settings: {
          video: {
            mode_id: "image_to_video",
            request_duration_seconds: 5.0,
            common_options: { motion_bucket_id: 127 },
            prompt_override: "server camera pan",
          },
        },
      },
    };

    const stored: StoredShotDraft = {
      projectId: "p1",
      shotId: "shot-123",
      baselineVersion: 2, // older baseline
      draft: {
        image_prompt: serverShotWithGen.image_prompt, // unchanged
        video_prompt: serverShotWithGen.video_prompt, // unchanged
        dialogue: serverShotWithGen.dialogue, // unchanged
        director_state: {
          generation_settings: {
            video: {
              mode_id: "image_to_video",
              request_duration_seconds: 3.0, // conflicting
              common_options: { motion_bucket_id: 50 }, // conflicting
              prompt_override: "draft local pan", // conflicting
            },
          },
        },
      },
      updatedAt: new Date().toISOString(),
    };

    const result = detectDraftConflicts(serverShotWithGen, stored);
    expect(result.hasConflict).toBe(true);
    const conflictFields = result.conflicts.map((c) => c.field);
    expect(conflictFields).toContain("generation_settings.video.request_duration_seconds");
    expect(conflictFields).toContain("generation_settings.video.common_options");
    expect(conflictFields).toContain("generation_settings.video.prompt_override");
  });

  it.each(["mode_id", "request_duration_seconds", "prompt_override"])(
    "requires a decision before restoring an old draft over a new server %s",
    (field) => {
      const server = {
        ...mockShot,
        director_state: {
          generation_settings: {
            video: { [field]: field === "request_duration_seconds" ? 4 : "new value" },
          },
        },
      };
      const stored: StoredShotDraft = {
        projectId: "p1",
        shotId: server.id,
        baselineVersion: 1,
        draft: {
          image_prompt: server.image_prompt,
          video_prompt: server.video_prompt,
          dialogue: server.dialogue,
          director_state: { generation_settings: { video: {} } },
        },
        updatedAt: new Date().toISOString(),
      };
      expect(detectDraftConflicts(server, stored).conflicts.map((item) => item.field)).toContain(
        `generation_settings.video.${field}`,
      );
    },
  );

  it("rebases local edits without replacing unrelated new server values", () => {
    const baseline = shotDraftFromServer(mockShot);
    const stored: StoredShotDraft = {
      projectId: "p1",
      shotId: mockShot.id,
      baselineVersion: 2,
      baseline,
      draft: { ...baseline, image_prompt: "local image" },
      updatedAt: "now",
    };
    const server = {
      ...mockShot,
      version: 3,
      video_prompt: "new server video",
      director_state: { generation_settings: { video: { request_duration_seconds: 4 } } },
    };
    expect(detectDraftConflicts(server, stored).conflicts).toEqual([]);
    const restored = restoreShotDraft(server, stored);
    expect(restored.image_prompt).toBe("local image");
    expect(restored.video_prompt).toBe("new server video");
    expect(restored.director_state).toEqual(server.director_state);
  });

  it("requires per-field choices and preserves explicit zero and removed overrides", () => {
    const base = {
      ...mockShot,
      director_state: {
        generation_settings: {
          video: { common_options: { seed: 1 }, request_duration_seconds: 5 },
        },
      },
    };
    const baseline = shotDraftFromServer(base);
    const stored: StoredShotDraft = {
      projectId: "p1",
      shotId: base.id,
      baselineVersion: 2,
      baseline,
      draft: {
        ...baseline,
        image_prompt: "local image",
        director_state: { generation_settings: { video: { common_options: { seed: 0 } } } },
      },
      updatedAt: "now",
    };
    const server = {
      ...base,
      version: 3,
      image_prompt: "server image",
      director_state: {
        generation_settings: {
          video: { common_options: { seed: 22 }, request_duration_seconds: 4 },
        },
      },
    };
    expect(() => restoreShotDraft(server, stored)).toThrow("逐项选择");
    const restored = restoreShotDraft(server, stored, {
      image_prompt: "server",
      "generation_settings.video.common_options.seed": "local",
      "generation_settings.video.request_duration_seconds": "server",
    });
    expect(restored.image_prompt).toBe("server image");
    expect(restored.director_state).toEqual({
      generation_settings: { video: { common_options: { seed: 0 }, request_duration_seconds: 4 } },
    });
  });
});
