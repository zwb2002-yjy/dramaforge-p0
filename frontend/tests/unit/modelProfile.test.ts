/**
 * Model-profile pure helpers (spec §30/§77/§78) — simple-mode mapping.
 * ``bindings`` is the single source of truth; simple mode is a batch patch.
 */

import { describe, expect, it } from "vitest";
import { SIMPLE_MODE_SLOT_GROUPS, simpleModeToBindings } from "../../src/lib/modelProfile";

describe("SIMPLE_MODE_SLOT_GROUPS", () => {
  it("maps LLM/Image/Video to the documented slot groups (spec §78)", () => {
    expect(SIMPLE_MODE_SLOT_GROUPS).toEqual({
      llm: ["planning.brief", "planning.script", "planning.storyboard"],
      image: ["visual.character", "visual.storyboard", "visual.keyframe"],
      video: ["video.shot"],
    });
  });
});

describe("simpleModeToBindings", () => {
  it("generates the bindings patch for a full selection", () => {
    const bindings = simpleModeToBindings({
      llm: "test/text-a",
      image: "test/image-a",
      video: "test/video-a",
    });
    expect(bindings["planning.brief"]).toEqual({ model_id: "test/text-a" });
    expect(bindings["planning.script"]).toEqual({ model_id: "test/text-a" });
    expect(bindings["planning.storyboard"]).toEqual({ model_id: "test/text-a" });
    expect(bindings["visual.character"]).toEqual({ model_id: "test/image-a" });
    expect(bindings["visual.storyboard"]).toEqual({ model_id: "test/image-a" });
    expect(bindings["visual.keyframe"]).toEqual({ model_id: "test/image-a" });
    expect(bindings["video.shot"]).toEqual({ model_id: "test/video-a" });
  });

  it("skips groups the user left unset", () => {
    const bindings = simpleModeToBindings({ llm: "test/text-a" });
    expect(Object.keys(bindings)).toEqual(["planning.brief", "planning.script", "planning.storyboard"]);
    expect(bindings["video.shot"]).toBeUndefined();
  });

  it("returns an empty patch when nothing is selected", () => {
    expect(simpleModeToBindings({})).toEqual({});
  });
});
