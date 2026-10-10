import { describe, expect, it } from "vitest";
import { cropClip, timelineGeometry } from "../../src/features/editing/timelineGeometry";
import type { EditableClip } from "../../src/features/editing/useTimelineDraft";

const clip: EditableClip = {
  id: "clip",
  shot_id: "shot",
  artifact_id: "formal-video",
  duration_seconds: 2,
  source_in_seconds: 0.15,
  source_out_seconds: 0.55,
  subtitle: "对白",
  audio_id: "voice",
  audio_volume: 0.25,
};

describe("draft track editing", () => {
  it.each(["in", "out"] as const)(
    "crops %s with the current speed and retains production references",
    (edge) => {
      const cropped = cropClip(clip, edge, 0.5)!;
      expect(cropped.duration_seconds).toBe(1.5);
      expect(cropped.source_in_seconds).toBe(edge === "in" ? 0.25 : 0.15);
      expect(cropped.source_out_seconds).toBe(edge === "out" ? 0.45 : 0.55);
      expect(cropped).toMatchObject({
        id: "clip",
        shot_id: "shot",
        artifact_id: "formal-video",
        subtitle: "对白",
        audio_id: "voice",
        audio_volume: 0.25,
      });
      expect(clip.duration_seconds).toBe(2);
    },
  );
  it("prevents an inverted or empty source interval and rejects invalid drafts", () => {
    const tiny = cropClip(clip, "in", 100)!;
    expect(Number(tiny.source_out_seconds)).toBeGreaterThan(Number(tiny.source_in_seconds));
    expect(Number(tiny.duration_seconds)).toBeGreaterThan(0);
    expect(cropClip(clip, "in", -1)).toBeNull();
    expect(cropClip({ ...clip, source_out_seconds: 0.1 }, "out", 0.1)).toBeNull();
    expect(cropClip({ ...clip, duration_seconds: "NaN" }, "in", 0.1)).toBeNull();
  });
  it("shows overlapping cuts instead of adding their durations, and marks invalid transitions", () => {
    const cut = { ...clip, id: "next", transition: { kind: "crossfade", duration_seconds: 0.25 } };
    const layout = timelineGeometry([clip, cut]);
    expect(layout.items[1]).toMatchObject({ startMs: 1750, endMs: 3750, overlapMs: 250 });
    expect(layout.durationMs).toBe(3750);
    expect(layout.valid).toBe(true);
    expect(
      timelineGeometry([clip, { ...cut, transition: { kind: "crossfade", duration_seconds: 2 } }])
        .valid,
    ).toBe(false);
    expect(timelineGeometry([{ ...clip, transition: "unknown" }]).valid).toBe(false);
  });
});
